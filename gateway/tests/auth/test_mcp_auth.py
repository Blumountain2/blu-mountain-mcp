"""Unit tests for the MCP Auth App install/callback flow (spec Section
4.1), mirroring test_hubspot_oauth.py's patterns for the parallel app."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from db import get_pool

from auth import decrypt, derive_tenant_key, mcp_auth
from auth.hubspot_oauth import HubSpotOAuthError
from auth.mcp_auth import McpTokenResult

app = FastAPI()
app.include_router(mcp_auth.router)


@pytest.mark.asyncio
async def test_install_mcp_auth_stores_state_and_redirects():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/install/mcp-auth", follow_redirects=False)

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("https://mcp.hubspot.com/oauth/authorize/user")
    assert "code_challenge=" in location
    assert "client_id=test-mcp-client-id" in location

    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM oauth_states")
    assert row is not None


@pytest.mark.asyncio
async def test_callback_mcp_auth_rejects_unknown_state():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/callback/mcp-auth", params={"code": "abc", "state": "does-not-exist"}
        )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("text/html")
    assert "/install/mcp-auth" in response.text


@pytest.mark.asyncio
async def test_callback_mcp_auth_missing_params_renders_error_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/callback/mcp-auth")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
async def test_callback_mcp_auth_token_exchange_failure_renders_error_page(monkeypatch):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier) VALUES ($1, $2)",
        "state-for-failure",
        "verifier",
    )
    monkeypatch.setattr(
        mcp_auth,
        "exchange_code",
        AsyncMock(side_effect=HubSpotOAuthError("invalid_grant", "code expired")),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/callback/mcp-auth", params={"code": "abc", "state": "state-for-failure"}
        )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "invalid_grant" in response.text


@pytest.mark.asyncio
async def test_callback_mcp_auth_requires_existing_tenant(monkeypatch):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier) VALUES ($1, $2)",
        "valid-state-no-tenant",
        "verifier",
    )

    fake_result = McpTokenResult(
        hub_id="no-such-tenant",
        access_token="fake-access-token",
        refresh_token="fake-refresh-token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    monkeypatch.setattr(mcp_auth, "exchange_code", AsyncMock(return_value=fake_result))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/callback/mcp-auth", params={"code": "abc", "state": "valid-state-no-tenant"}
        )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("text/html")
    assert "/install" in response.text

    token_row = await pool.fetchrow(
        "SELECT * FROM mcp_tokens WHERE hub_id = $1", "no-such-tenant"
    )
    assert token_row is None


@pytest.mark.asyncio
async def test_callback_mcp_auth_rejects_uninstalled_tenant(monkeypatch):
    # A tenants row is never deleted on uninstall (only flagged, see
    # token_vault.py) — a stale/retried MCP Auth App install link for a
    # since-uninstalled portal must still be rejected, not waved through
    # into a half-installed state (a live MCP Auth token with no valid
    # Public App token).
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'uninstalled')",
        "was-uninstalled",
    )
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier) VALUES ($1, $2)",
        "valid-state-uninstalled-tenant",
        "verifier",
    )

    fake_result = McpTokenResult(
        hub_id="was-uninstalled",
        access_token="fake-access-token",
        refresh_token="fake-refresh-token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    monkeypatch.setattr(mcp_auth, "exchange_code", AsyncMock(return_value=fake_result))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/callback/mcp-auth", params={"code": "abc", "state": "valid-state-uninstalled-tenant"}
        )

    assert response.status_code == 409

    token_row = await pool.fetchrow(
        "SELECT * FROM mcp_tokens WHERE hub_id = $1", "was-uninstalled"
    )
    assert token_row is None


@pytest.mark.asyncio
async def test_callback_mcp_auth_accepts_valid_state_and_persists_token(monkeypatch):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id) VALUES ($1)",
        "12345",
    )
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier) VALUES ($1, $2)",
        "valid-state",
        "verifier",
    )

    fake_result = McpTokenResult(
        hub_id="12345",
        access_token="fake-mcp-access-token",
        refresh_token="fake-mcp-refresh-token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    monkeypatch.setattr(mcp_auth, "exchange_code", AsyncMock(return_value=fake_result))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/callback/mcp-auth", params={"code": "abc", "state": "valid-state"}
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "12345" in response.text

    token_row = await pool.fetchrow("SELECT * FROM mcp_tokens WHERE hub_id = $1", "12345")
    assert token_row is not None
    # The vaulted row must never contain the raw token value.
    assert "fake-mcp-access-token" not in token_row["encrypted_access_token"]
    assert "fake-mcp-refresh-token" not in token_row["encrypted_refresh_token"]

    audit_rows = await pool.fetch("SELECT * FROM audit_log WHERE hub_id = $1", "12345")
    assert audit_rows
    for row in audit_rows:
        assert "fake-mcp-access-token" not in str(row["detail"])
        assert "fake-mcp-refresh-token" not in str(row["detail"])


@pytest.mark.asyncio
async def test_callback_mcp_auth_isolates_tokens_across_tenants(monkeypatch):
    """Two distinct tenants completing the MCP Auth App install must never
    have their tokens cross-contaminate, even though both flow through the
    same shared oauth_states table and the same callback route — the
    CLAUDE.md non-negotiable multi-tenant isolation test this code path
    was missing (mirrors test_hubspot_client.py's
    test_pull_uses_only_this_tenants_token_never_anothers)."""
    pool = await get_pool()
    await pool.execute("INSERT INTO tenants (hub_id) VALUES ($1)", "tenant-a")
    await pool.execute("INSERT INTO tenants (hub_id) VALUES ($1)", "tenant-b")
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier) VALUES ($1, $2)",
        "state-tenant-a",
        "verifier-a",
    )
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier) VALUES ($1, $2)",
        "state-tenant-b",
        "verifier-b",
    )

    results_by_verifier = {
        "verifier-a": McpTokenResult(
            hub_id="tenant-a",
            access_token="access-a",
            refresh_token="refresh-a",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ),
        "verifier-b": McpTokenResult(
            hub_id="tenant-b",
            access_token="access-b",
            refresh_token="refresh-b",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ),
    }

    async def fake_exchange_code(code, code_verifier):
        return results_by_verifier[code_verifier]

    monkeypatch.setattr(mcp_auth, "exchange_code", fake_exchange_code)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response_a = await client.get(
            "/callback/mcp-auth", params={"code": "code-a", "state": "state-tenant-a"}
        )
        response_b = await client.get(
            "/callback/mcp-auth", params={"code": "code-b", "state": "state-tenant-b"}
        )

    assert response_a.status_code == 200
    assert response_b.status_code == 200

    row_a = await pool.fetchrow("SELECT * FROM mcp_tokens WHERE hub_id = $1", "tenant-a")
    row_b = await pool.fetchrow("SELECT * FROM mcp_tokens WHERE hub_id = $1", "tenant-b")

    key_a = derive_tenant_key("tenant-a")
    key_b = derive_tenant_key("tenant-b")

    assert decrypt(row_a["encrypted_access_token"], key_a) == "access-a"
    assert decrypt(row_b["encrypted_access_token"], key_b) == "access-b"
    # Neither tenant's token is ever decryptable under the other's derived key.
    with pytest.raises(Exception):
        decrypt(row_a["encrypted_access_token"], key_b)


@pytest.mark.asyncio
async def test_callback_mcp_auth_state_is_single_use(monkeypatch):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id) VALUES ($1)",
        "999",
    )
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier) VALUES ($1, $2)",
        "one-shot-state",
        "verifier",
    )
    fake_result = McpTokenResult(
        hub_id="999",
        access_token="tok",
        refresh_token="ref",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    monkeypatch.setattr(mcp_auth, "exchange_code", AsyncMock(return_value=fake_result))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get(
            "/callback/mcp-auth", params={"code": "abc", "state": "one-shot-state"}
        )
        second = await client.get(
            "/callback/mcp-auth", params={"code": "abc", "state": "one-shot-state"}
        )

    assert first.status_code == 200
    assert second.status_code == 403


def test_hub_id_from_fields_reads_confirmed_real_field_name():
    # Confirmed live against a real MCP Auth App install (see design.md):
    # the token exchange response body's portal identifier field is
    # "hub_id". The other candidates stay in the list for defense in
    # depth, but this is the one that must keep working.
    assert mcp_auth._hub_id_from_fields({"hub_id": "148997330"}) == "148997330"


def test_hub_id_from_fields_returns_none_when_absent():
    assert mcp_auth._hub_id_from_fields({"active": True}) is None


def test_hub_id_from_fields_skips_a_present_but_null_candidate():
    # An earlier candidate present with a null value must not win over a
    # later candidate that actually has the real value.
    assert mcp_auth._hub_id_from_fields({"hub_id": None, "portalId": "148997330"}) == "148997330"


@pytest.mark.asyncio
async def test_exchange_code_raises_when_hub_id_missing_from_token_body(monkeypatch):
    class _FakeResponse:
        status_code = 200

        def json(self):
            return {
                "access_token": "tok",
                "refresh_token": "ref",
                "expires_in": 3600,
            }

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, data):
            return _FakeResponse()

    monkeypatch.setattr(mcp_auth.httpx, "AsyncClient", lambda: _FakeAsyncClient())

    with pytest.raises(mcp_auth.HubSpotOAuthError):
        await mcp_auth.exchange_code("code", "verifier")
