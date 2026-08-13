"""SC-5: HubSpot's app-lifecycle webhook signature validation and replay
protection, exercised through the real /webhooks/hubspot/uninstall route."""

import hashlib
import hmac
import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from config import settings
from db import get_pool

from auth import derive_tenant_key, encrypt, token_vault
from auth.token_vault import verify_hubspot_webhook_signature

app = FastAPI()
app.include_router(token_vault.router)


def _sign(body: bytes) -> str:
    return hmac.new(settings.hubspot_app_client_secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_hubspot_webhook_signature_valid():
    body = b'{"portalId": "123"}'
    assert verify_hubspot_webhook_signature(body, _sign(body), settings.hubspot_app_client_secret) is True


def test_verify_hubspot_webhook_signature_invalid():
    body = b'{"portalId": "123"}'
    assert verify_hubspot_webhook_signature(body, "not-the-right-signature", settings.hubspot_app_client_secret) is False


@pytest.mark.asyncio
async def test_uninstall_webhook_rejects_bad_signature():
    body = b'{"portalId": "123"}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/hubspot/uninstall",
            content=body,
            headers={
                "X-HubSpot-Signature-V3": "bad-signature",
                "X-HubSpot-Request-Timestamp": str(int(time.time() * 1000)),
            },
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_uninstall_webhook_rejects_stale_request():
    body = b'{"portalId": "123"}'
    stale_ts = str(int((time.time() - 600) * 1000))  # 10 minutes old
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/hubspot/uninstall",
            content=body,
            headers={
                "X-HubSpot-Signature-V3": _sign(body),
                "X-HubSpot-Request-Timestamp": stale_ts,
            },
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_uninstall_webhook_accepts_valid_signature_and_invalidates_tenant():
    pool = await get_pool()
    key = derive_tenant_key("456")
    await pool.execute("INSERT INTO tenants (hub_id) VALUES ($1)", "456")
    await pool.execute(
        """
        INSERT INTO tokens (hub_id, encrypted_access_token, encrypted_refresh_token, expires_at)
        VALUES ($1, $2, $3, now() + interval '1 hour')
        """,
        "456",
        encrypt("access", key),
        encrypt("refresh", key),
    )

    body = b'{"portalId": "456"}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/hubspot/uninstall",
            content=body,
            headers={
                "X-HubSpot-Signature-V3": _sign(body),
                "X-HubSpot-Request-Timestamp": str(int(time.time() * 1000)),
            },
        )

    assert response.status_code == 200
    token_row = await pool.fetchrow("SELECT * FROM tokens WHERE hub_id = $1", "456")
    assert token_row is None


@pytest.mark.asyncio
async def test_uninstall_webhook_also_invalidates_mcp_auth_token():
    pool = await get_pool()
    key = derive_tenant_key("789")
    await pool.execute("INSERT INTO tenants (hub_id) VALUES ($1)", "789")
    await pool.execute(
        """
        INSERT INTO tokens (hub_id, encrypted_access_token, encrypted_refresh_token, expires_at)
        VALUES ($1, $2, $3, now() + interval '1 hour')
        """,
        "789",
        encrypt("access", key),
        encrypt("refresh", key),
    )
    await pool.execute(
        """
        INSERT INTO mcp_tokens (hub_id, encrypted_access_token, encrypted_refresh_token, expires_at)
        VALUES ($1, $2, $3, now() + interval '1 hour')
        """,
        "789",
        encrypt("mcp-access", key),
        encrypt("mcp-refresh", key),
    )

    body = b'{"portalId": "789"}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/hubspot/uninstall",
            content=body,
            headers={
                "X-HubSpot-Signature-V3": _sign(body),
                "X-HubSpot-Request-Timestamp": str(int(time.time() * 1000)),
            },
        )

    assert response.status_code == 200
    mcp_token_row = await pool.fetchrow("SELECT * FROM mcp_tokens WHERE hub_id = $1", "789")
    assert mcp_token_row is None


@pytest.mark.asyncio
async def test_uninstall_webhook_never_touches_another_tenants_mcp_token():
    """Cross-tenant isolation for the atomic vault+mcp_vault invalidation:
    uninstalling one tenant must never delete or affect another tenant's
    mcp_tokens row, tokens row, or install_status."""
    pool = await get_pool()
    key_uninstalled = derive_tenant_key("uninstall-me")
    key_other = derive_tenant_key("leave-me-alone")

    for hub_id, key in (("uninstall-me", key_uninstalled), ("leave-me-alone", key_other)):
        await pool.execute("INSERT INTO tenants (hub_id) VALUES ($1)", hub_id)
        await pool.execute(
            """
            INSERT INTO tokens (hub_id, encrypted_access_token, encrypted_refresh_token, expires_at)
            VALUES ($1, $2, $3, now() + interval '1 hour')
            """,
            hub_id,
            encrypt("access", key),
            encrypt("refresh", key),
        )
        await pool.execute(
            """
            INSERT INTO mcp_tokens (hub_id, encrypted_access_token, encrypted_refresh_token, expires_at)
            VALUES ($1, $2, $3, now() + interval '1 hour')
            """,
            hub_id,
            encrypt("mcp-access", key),
            encrypt("mcp-refresh", key),
        )

    body = b'{"portalId": "uninstall-me"}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/hubspot/uninstall",
            content=body,
            headers={
                "X-HubSpot-Signature-V3": _sign(body),
                "X-HubSpot-Request-Timestamp": str(int(time.time() * 1000)),
            },
        )

    assert response.status_code == 200
    assert await pool.fetchrow("SELECT * FROM tokens WHERE hub_id = $1", "uninstall-me") is None
    assert await pool.fetchrow("SELECT * FROM mcp_tokens WHERE hub_id = $1", "uninstall-me") is None

    other_token_row = await pool.fetchrow("SELECT * FROM tokens WHERE hub_id = $1", "leave-me-alone")
    other_mcp_row = await pool.fetchrow("SELECT * FROM mcp_tokens WHERE hub_id = $1", "leave-me-alone")
    other_tenant_row = await pool.fetchrow(
        "SELECT install_status FROM tenants WHERE hub_id = $1", "leave-me-alone"
    )
    assert other_token_row is not None
    assert other_mcp_row is not None
    assert other_tenant_row["install_status"] == "installed"
