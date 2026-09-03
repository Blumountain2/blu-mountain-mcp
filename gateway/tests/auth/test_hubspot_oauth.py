"""Task 1.9: unit tests for PKCE generation, state validation, and
error-field parsing."""

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from db import get_pool

from auth import hubspot_oauth
from auth.hubspot_oauth import (
    HubSpotOAuthError,
    TokenResult,
    _parse_token_error,
    generate_pkce_pair,
)

app = FastAPI()
app.include_router(hubspot_oauth.router)


def test_generate_pkce_pair_verifier_length():
    verifier, _challenge = generate_pkce_pair()
    assert 43 <= len(verifier) <= 128


def test_generate_pkce_pair_challenge_matches_s256():
    verifier, challenge = generate_pkce_pair()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    assert challenge == expected


def test_parse_token_error_rfc6749_fields():
    response = httpx.Response(
        400, json={"error": "invalid_grant", "error_description": "code expired"}
    )
    error = _parse_token_error(response)
    assert error.error == "invalid_grant"
    assert error.error_description == "code expired"


def test_parse_token_error_hubspot_native_fields():
    response = httpx.Response(400, json={"status": "BAD_AUTH_CODE", "message": "bad code"})
    error = _parse_token_error(response)
    assert error.error == "BAD_AUTH_CODE"
    assert error.error_description == "bad code"


def test_parse_token_error_never_includes_client_secret():
    response = httpx.Response(400, json={"error": "invalid_client", "error_description": "nope"})
    error = _parse_token_error(response)
    assert "test-client-secret" not in str(error)


@pytest.mark.asyncio
async def test_install_stores_state_and_redirects():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/install", follow_redirects=False)

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert "code_challenge=" in location
    assert "client_id=test-app-client-id" in location

    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM oauth_states")
    assert row is not None


@pytest.mark.asyncio
async def test_install_omits_optional_scope_param_when_not_configured():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/install", follow_redirects=False)

    assert "optional_scope=" not in response.headers["location"]


@pytest.mark.asyncio
async def test_install_includes_optional_scope_param_when_configured(monkeypatch):
    """Confirmed live (openspec/changes/hubspot-rest-api-pivot): requesting
    marketing.campaigns.read as a required `scope` hard-failed a real
    install on an account without Marketing Hub Professional+ ("your
    account lacks access to the required scopes"). HubSpot's separate
    `optional_scope` param is what degrades gracefully instead — a scope
    listed there is just omitted from the grant if the account can't have
    it, rather than failing the whole authorization."""
    monkeypatch.setattr(hubspot_oauth.settings, "hubspot_optional_scopes", "marketing.campaigns.read")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/install", follow_redirects=False)

    assert "optional_scope=marketing.campaigns.read" in response.headers["location"]


@pytest.mark.asyncio
async def test_install_with_portal_name_stores_it():
    # HubSpot has no API for a portal's human-readable name (confirmed
    # against its account-info endpoint and community docs) — whoever sends
    # the install link supplies it instead, via this optional query param.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/install", params={"portal_name": "Blu Mountain & Gumpper"}, follow_redirects=False
        )

    assert response.status_code in (302, 307)
    pool = await get_pool()
    row = await pool.fetchrow("SELECT portal_name FROM oauth_states")
    assert row["portal_name"] == "Blu Mountain & Gumpper"


@pytest.mark.asyncio
async def test_install_with_blank_portal_name_stores_null():
    # An empty string is not NULL to Postgres — storing "" here would defeat
    # the COALESCE fallback to hub_domain on read, and would look like a
    # deliberately-set (blank) name that a later reinstall's COALESCE
    # wouldn't touch. Must be normalized to NULL, not stored as "".
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/install", params={"portal_name": ""}, follow_redirects=False)

    pool = await get_pool()
    row = await pool.fetchrow("SELECT portal_name FROM oauth_states")
    assert row["portal_name"] is None


@pytest.mark.asyncio
async def test_install_with_whitespace_only_portal_name_stores_null():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/install", params={"portal_name": "   "}, follow_redirects=False)

    pool = await get_pool()
    row = await pool.fetchrow("SELECT portal_name FROM oauth_states")
    assert row["portal_name"] is None


@pytest.mark.asyncio
async def test_install_trims_surrounding_whitespace_from_portal_name():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get(
            "/install", params={"portal_name": "  Blu Mountain & Gumpper  "}, follow_redirects=False
        )

    pool = await get_pool()
    row = await pool.fetchrow("SELECT portal_name FROM oauth_states")
    assert row["portal_name"] == "Blu Mountain & Gumpper"


@pytest.mark.asyncio
async def test_install_without_portal_name_leaves_it_null():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/install", follow_redirects=False)

    pool = await get_pool()
    row = await pool.fetchrow("SELECT portal_name FROM oauth_states")
    assert row["portal_name"] is None


@pytest.mark.asyncio
async def test_callback_rejects_unknown_state():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/callback", params={"code": "abc", "state": "does-not-exist"})

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("text/html")
    assert "/install" in response.text


@pytest.mark.asyncio
async def test_callback_missing_params_renders_error_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/callback")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
async def test_callback_token_exchange_failure_renders_error_page(monkeypatch):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier) VALUES ($1, $2)",
        "state-for-failure",
        "verifier",
    )
    monkeypatch.setattr(
        hubspot_oauth,
        "exchange_code",
        AsyncMock(side_effect=HubSpotOAuthError("invalid_grant", "code expired")),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/callback", params={"code": "abc", "state": "state-for-failure"}
        )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "invalid_grant" in response.text


@pytest.mark.asyncio
async def test_callback_accepts_valid_state_and_persists_tenant(monkeypatch):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier) VALUES ($1, $2)",
        "valid-state",
        "verifier",
    )

    fake_result = TokenResult(
        hub_id="12345",
        access_token="fake-access-token",
        refresh_token="fake-refresh-token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    monkeypatch.setattr(hubspot_oauth, "exchange_code", AsyncMock(return_value=fake_result))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/callback", params={"code": "abc", "state": "valid-state"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "12345" in response.text
    # Single-install flow (openspec/changes/hubspot-rest-api-pivot): no
    # "continue setup" link to a second install step anymore.
    assert "/install/mcp-auth" not in response.text

    tenant_row = await pool.fetchrow("SELECT * FROM tenants WHERE hub_id = $1", "12345")
    assert tenant_row is not None
    token_row = await pool.fetchrow("SELECT * FROM tokens WHERE hub_id = $1", "12345")
    assert token_row is not None
    # The vaulted row must never contain the raw token value.
    assert "fake-access-token" not in token_row["encrypted_access_token"]

    # Task 2.12: the raw token must never appear in an audit log entry either.
    audit_rows = await pool.fetch("SELECT * FROM audit_log WHERE hub_id = $1", "12345")
    assert audit_rows
    for row in audit_rows:
        assert "fake-access-token" not in str(row["detail"])
        assert "fake-refresh-token" not in str(row["detail"])


@pytest.mark.asyncio
async def test_callback_persists_portal_name_and_hub_domain(monkeypatch):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier, portal_name) VALUES ($1, $2, $3)",
        "state-with-name",
        "verifier",
        "Blu Mountain & Gumpper",
    )
    fake_result = TokenResult(
        hub_id="55555",
        access_token="tok",
        refresh_token="ref",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        hub_domain="blumountain.me",
    )
    monkeypatch.setattr(hubspot_oauth, "exchange_code", AsyncMock(return_value=fake_result))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/callback", params={"code": "abc", "state": "state-with-name"}
        )

    assert response.status_code == 200
    tenant_row = await pool.fetchrow("SELECT * FROM tenants WHERE hub_id = $1", "55555")
    assert tenant_row["portal_name"] == "Blu Mountain & Gumpper"
    assert tenant_row["hub_domain"] == "blumountain.me"


@pytest.mark.asyncio
async def test_callback_reinstall_keeps_portal_name_but_refreshes_hub_domain(monkeypatch):
    # A manually-set name must survive a reconnect that doesn't repeat it —
    # hub_domain is a live technical fact, safe to always refresh; portal_name
    # is human-curated and must never be silently overwritten.
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id, portal_name, hub_domain) VALUES ($1, $2, $3)",
        "66666",
        "Blu Mountain & Gumpper",
        "old-domain.example.com",
    )
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier) VALUES ($1, $2)",
        "state-reinstall",
        "verifier",
    )
    fake_result = TokenResult(
        hub_id="66666",
        access_token="tok",
        refresh_token="ref",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        hub_domain="new-domain.example.com",
    )
    monkeypatch.setattr(hubspot_oauth, "exchange_code", AsyncMock(return_value=fake_result))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/callback", params={"code": "abc", "state": "state-reinstall"}
        )

    assert response.status_code == 200
    tenant_row = await pool.fetchrow("SELECT * FROM tenants WHERE hub_id = $1", "66666")
    assert tenant_row["portal_name"] == "Blu Mountain & Gumpper"
    assert tenant_row["hub_domain"] == "new-domain.example.com"


@pytest.mark.asyncio
async def test_persist_new_tenant_treats_blank_portal_name_as_null_even_if_caller_didnt_normalize():
    # Defense in depth: /install normalizes blank/whitespace-only names to
    # None itself, but _persist_new_tenant must not rely solely on every
    # caller getting that right — an empty string reaching the SQL layer
    # would otherwise look like a deliberately-set (blank) name.
    from auth.hubspot_oauth import _persist_new_tenant

    fake_result = TokenResult(
        hub_id="77777",
        access_token="tok",
        refresh_token="ref",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        hub_domain="blumountain.me",
    )
    await _persist_new_tenant(fake_result, "   ")

    pool = await get_pool()
    tenant_row = await pool.fetchrow("SELECT * FROM tenants WHERE hub_id = $1", "77777")
    assert tenant_row["portal_name"] is None
    assert tenant_row["hub_domain"] == "blumountain.me"


@pytest.mark.asyncio
async def test_persist_new_tenant_reinstall_keeps_hub_domain_if_new_fetch_returns_blank():
    # Symmetric with the portal_name protection: a reinstall whose HubSpot
    # response happens to omit hub_domain must not erase a previously-known
    # good value — hub_domain is normally always refreshed, but "refreshed
    # with nothing" should never mean "erased."
    from auth.hubspot_oauth import _persist_new_tenant

    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id, portal_name, hub_domain) VALUES ($1, $2, $3)",
        "88888", "Blu Mountain & Gumpper", "blumountain.me",
    )

    fake_result = TokenResult(
        hub_id="88888",
        access_token="tok",
        refresh_token="ref",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        hub_domain=None,
    )
    await _persist_new_tenant(fake_result, None)

    tenant_row = await pool.fetchrow("SELECT * FROM tenants WHERE hub_id = $1", "88888")
    assert tenant_row["portal_name"] == "Blu Mountain & Gumpper"
    assert tenant_row["hub_domain"] == "blumountain.me"


@pytest.mark.asyncio
async def test_callback_state_is_single_use(monkeypatch):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier) VALUES ($1, $2)",
        "one-shot-state",
        "verifier",
    )
    fake_result = TokenResult(
        hub_id="999",
        access_token="tok",
        refresh_token="ref",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    monkeypatch.setattr(hubspot_oauth, "exchange_code", AsyncMock(return_value=fake_result))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/callback", params={"code": "abc", "state": "one-shot-state"})
        second = await client.get("/callback", params={"code": "abc", "state": "one-shot-state"})

    assert first.status_code == 200
    assert second.status_code == 403
