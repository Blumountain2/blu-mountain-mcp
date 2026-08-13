"""HubSpot MCP Auth App OAuth v3 + PKCE install/callback flow (spec Section
4.1). A separate app from the Public App in hubspot_oauth.py — HubSpot's
remote MCP endpoint (mcp.hubspot.com) does not accept the Public App's
CRM-scoped token; it requires its own credential, installed per tenant the
same way, per the spec: "The resulting Client ID and Client Secret are
shared across all tenants; the per-tenant tokens are what differ. Every
customer installs this same app into their own portal."

Deliberately kept separate from hubspot_oauth.py rather than merged into
one flow, so nothing about the already-verified Public App install path
changes shape.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from config import settings
from db import get_pool

from .hubspot_oauth import HubSpotOAuthError, _parse_token_error, generate_pkce_pair
from .pages import error_page, install_success_page
from .security import record_audit

logger = structlog.get_logger()

router = APIRouter()

# Discovered from mcp.hubspot.com's own RFC 8414 authorization-server
# metadata (https://mcp.hubspot.com/.well-known/oauth-authorization-server)
# — a distinct issuer/host from the Public App's app.hubspot.com/api.hubapi.com,
# confirmed to support authorization_code + refresh_token grants and S256 PKCE,
# the same shape hubspot_oauth.py already relies on.
AUTHORIZE_URL = "https://mcp.hubspot.com/oauth/authorize/user"
TOKEN_URL = "https://mcp.hubspot.com/oauth/v3/token"

_STATE_TTL = timedelta(minutes=10)

# Confirmed live against a real install (see design.md's decision log):
# the token exchange response body itself carries the portal identifier
# under one of these field names, tried in order. The access token itself
# is opaque, not a JWT, and mcp.hubspot.com's introspection endpoint
# returns only RFC 7662's minimal {"active": true/false} with nothing else
# — both were checked and ruled out as real sources, so this is the one
# real place hub_id lives, not one candidate location among several.
_HUB_ID_FIELD_CANDIDATES = ("hub_id", "hubId", "portalId", "portal_id")


@dataclass
class McpTokenResult:
    hub_id: str
    access_token: str
    refresh_token: str
    expires_at: datetime


@router.get("/install/mcp-auth")
async def install_mcp_auth() -> RedirectResponse:
    """Starts the MCP Auth App install for a client portal."""
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(32)

    pool = await get_pool()
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier) VALUES ($1, $2)",
        state,
        code_verifier,
    )

    params = {
        "client_id": settings.hubspot_mcp_client_id,
        "redirect_uri": settings.hubspot_mcp_redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    query = httpx.QueryParams(params)
    return RedirectResponse(f"{AUTHORIZE_URL}?{query}")


@router.get("/callback/mcp-auth")
async def callback_mcp_auth(request: Request) -> HTMLResponse:
    """Completes the MCP Auth App install: validates state, exchanges the
    code, persists the token pair into mcp_tokens (separate from the Public
    App's tokens table)."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or not state:
        return error_page(
            "Something Went Wrong",
            "This link is missing required information. Please start the "
            "connection process again.",
            400,
            request=request,
            retry_path="/install/mcp-auth",
        )

    pool = await get_pool()
    row = await pool.fetchrow(
        "DELETE FROM oauth_states WHERE state = $1 AND created_at > now() - $2::interval "
        "RETURNING code_verifier",
        state,
        _STATE_TTL,
    )
    if row is None:
        logger.warning("mcp_auth.state_mismatch")
        return error_page(
            "Link Expired",
            "This connection link has expired or was already used. Please "
            "start again.",
            403,
            request=request,
            retry_path="/install/mcp-auth",
        )

    code_verifier = row["code_verifier"]

    try:
        result = await exchange_code(code, code_verifier)
    except HubSpotOAuthError as exc:
        logger.warning("mcp_auth.token_exchange_failed", error=exc.error)
        return error_page(
            "Connection Failed",
            f"HubSpot reported an error completing this connection: {exc.error}. "
            "Please try again or contact support if this continues.",
            400,
            request=request,
            retry_path="/install/mcp-auth",
        )

    # mcp_tokens.hub_id references tenants(hub_id): this app must be
    # installed after the Public App (hubspot_oauth.py), which is what
    # creates that row. Checked explicitly here so a wrong install order
    # surfaces as a clear, actionable error instead of a raw FK-violation
    # 500 from the INSERT inside _persist_mcp_tenant. Checks
    # install_status = 'installed', not mere row existence — a tenant row
    # is never deleted on uninstall (only flagged, see token_vault.py), so
    # a stale/retried install link for a since-uninstalled portal must
    # still be rejected here rather than being waved through into a
    # half-installed state (a live MCP Auth token with no valid Public App
    # token). The check and the insert both run inside the SAME
    # transaction, under the same per-tenant advisory lock
    # vault.invalidate() uses (a lazy import — see token_vault.py's own
    # note on why its mcp_auth import is deferred the same way) — without
    # it, the uninstall webhook could flip install_status to 'uninstalled'
    # in the gap between this check and the insert, and this callback
    # would still persist a fresh mcp_tokens row anyway, reaching exactly
    # the half-installed state this check exists to prevent, just via a
    # timing race instead of wrong step ordering.
    from .token_vault import PUBLIC_APP_TOKEN_TABLE, acquire_tenant_lock

    async with pool.acquire() as conn:
        async with conn.transaction():
            await acquire_tenant_lock(conn, result.hub_id, PUBLIC_APP_TOKEN_TABLE)
            tenant_installed = await conn.fetchval(
                "SELECT 1 FROM tenants WHERE hub_id = $1 AND install_status = 'installed'",
                result.hub_id,
            )
            if not tenant_installed:
                logger.warning("mcp_auth.no_matching_tenant", hub_id=result.hub_id)
                return error_page(
                    "One Step Missing",
                    "The main HubSpot connection needs to be completed first, before "
                    "this second step.",
                    409,
                    request=request,
                    retry_path="/install",
                    retry_label="Go to step 1",
                )

            await _persist_mcp_tenant(result, conn=conn)

    await record_audit("mcp_auth_install_completed", hub_id=result.hub_id)

    logger.info("mcp_auth.install_complete", hub_id=result.hub_id)
    return install_success_page(
        "Setup Complete",
        result.hub_id,
        "This HubSpot portal is now fully connected to Blu Mountain's "
        "Intelligence System.",
        request=request,
    )


async def exchange_code(code: str, code_verifier: str) -> McpTokenResult:
    """Exchanges an authorization code for a token pair against the MCP
    Auth App's own token endpoint. hub_id comes directly from this same
    response body (confirmed live against a real install, see design.md) —
    no separate introspection call is needed."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.hubspot_mcp_client_id,
                "client_secret": settings.hubspot_mcp_client_secret,
                "redirect_uri": settings.hubspot_mcp_redirect_uri,
                "code": code,
                "code_verifier": code_verifier,
            },
        )
        if response.status_code != 200:
            raise _parse_token_error(response)

        body = response.json()
        access_token = body["access_token"]
        refresh_token = body["refresh_token"]
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=body["expires_in"])

        hub_id = _hub_id_from_fields(body)
        if hub_id is None:
            logger.error("mcp_auth.hub_id_not_in_token_body", response_keys=list(body.keys()))
            raise HubSpotOAuthError(
                "missing_hub_id",
                f"Token response had no recognized hub_id field: {list(body.keys())}",
            )

    return McpTokenResult(
        hub_id=hub_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )


def _hub_id_from_fields(source: dict) -> str | None:
    # Checks the value itself, not just key presence — a candidate field
    # that's present but null must fall through to the next candidate
    # instead of returning the literal string "None".
    for field in _HUB_ID_FIELD_CANDIDATES:
        value = source.get(field)
        if value is not None:
            return str(value)
    return None


async def refresh_token_pair(refresh_token: str) -> tuple[str, str, datetime]:
    """Refreshes an access/refresh token pair against the MCP Auth App's
    token endpoint. Same grant_type=refresh_token mechanism confirmed
    supported by mcp.hubspot.com's own RFC 8414 metadata."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.hubspot_mcp_client_id,
                "client_secret": settings.hubspot_mcp_client_secret,
                "refresh_token": refresh_token,
            },
        )
        if response.status_code != 200:
            raise _parse_token_error(response)

        body = response.json()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=body["expires_in"])
        return body["access_token"], body["refresh_token"], expires_at


async def _persist_mcp_tenant(result: McpTokenResult, conn) -> None:
    """Runs within the caller's existing transaction (see
    callback_mcp_auth) rather than acquiring its own connection, so the
    install-order check and this insert are atomic and share one
    advisory-lock scope."""
    from .crypto import derive_tenant_key, encrypt

    key = derive_tenant_key(result.hub_id)
    await conn.execute(
        """
        INSERT INTO mcp_tokens (hub_id, encrypted_access_token, encrypted_refresh_token, expires_at)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (hub_id) DO UPDATE SET
            encrypted_access_token = EXCLUDED.encrypted_access_token,
            encrypted_refresh_token = EXCLUDED.encrypted_refresh_token,
            expires_at = EXCLUDED.expires_at,
            last_refreshed_at = now()
        """,
        result.hub_id,
        encrypt(result.access_token, key),
        encrypt(result.refresh_token, key),
        result.expires_at,
    )
