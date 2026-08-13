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
    assert "/install/mcp-auth" in response.text

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
