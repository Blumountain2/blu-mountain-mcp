"""HubSpot Public App OAuth v3 + PKCE install/callback flow (Flow B).

Decision (task 1.8): HubSpot has no dedicated "v3 introspect" endpoint.
Token validation and hub_id discovery use GET /oauth/v1/access-tokens/{token}
immediately after exchange, since hub_id is required to key the vault and
is not returned by the token exchange response itself.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from config import settings
from db import get_pool

from .pages import error_page, install_success_page
from .security import record_audit

logger = structlog.get_logger()

router = APIRouter()

AUTHORIZE_URL = "https://app.hubspot.com/oauth/authorize"
TOKEN_URL = "https://api.hubapi.com/oauth/v3/token"
ACCESS_TOKEN_INFO_URL = "https://api.hubapi.com/oauth/v1/access-tokens/{token}"

_STATE_TTL = timedelta(minutes=10)


class HubSpotOAuthError(Exception):
    """Raised on a standardized RFC 6749 (or HubSpot-native) token error."""

    def __init__(self, error: str, error_description: str = ""):
        self.error = error
        self.error_description = error_description
        super().__init__(f"{error}: {error_description}")


@dataclass
class TokenResult:
    hub_id: str
    access_token: str
    refresh_token: str
    expires_at: datetime


def generate_pkce_pair() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge) per RFC 7636, S256 method."""
    code_verifier = secrets.token_urlsafe(64)[:128]
    if len(code_verifier) < 43:
        code_verifier = code_verifier.ljust(43, "a")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _parse_token_error(response: httpx.Response) -> HubSpotOAuthError:
    """Parses HubSpot's token-endpoint error body without ever logging credentials."""
    try:
        body = response.json()
    except ValueError:
        return HubSpotOAuthError("invalid_response", f"HTTP {response.status_code}")

    # Standard RFC 6749 fields, falling back to HubSpot's own {status, message}.
    error = body.get("error") or body.get("status") or "unknown_error"
    description = body.get("error_description") or body.get("message") or ""
    return HubSpotOAuthError(error, description)


@router.get("/install")
async def install() -> RedirectResponse:
    """Starts Flow B: redirects the client portal admin to HubSpot's authorization URL."""
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(32)

    pool = await get_pool()
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier) VALUES ($1, $2)",
        state,
        code_verifier,
    )

    params = {
        "client_id": settings.hubspot_app_client_id,
        "redirect_uri": settings.hubspot_redirect_uri,
        "scope": settings.hubspot_scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    query = httpx.QueryParams(params)
    return RedirectResponse(f"{AUTHORIZE_URL}?{query}")


@router.get("/callback")
async def callback(request: Request) -> HTMLResponse:
    """Completes Flow B: validates state, exchanges the code, persists the token pair."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or not state:
        return error_page(
            "Something Went Wrong",
            "This link is missing required information. Please start the "
            "connection process again.",
            400,
            request=request,
            retry_path="/install",
        )

    pool = await get_pool()
    row = await pool.fetchrow(
        "DELETE FROM oauth_states WHERE state = $1 AND created_at > now() - $2::interval "
        "RETURNING code_verifier",
        state,
        _STATE_TTL,
    )
    if row is None:
        logger.warning("hubspot_oauth.state_mismatch")
        return error_page(
            "Link Expired",
            "This connection link has expired or was already used. Please "
            "start again.",
            403,
            request=request,
            retry_path="/install",
        )

    code_verifier = row["code_verifier"]

    try:
        result = await exchange_code(code, code_verifier)
    except HubSpotOAuthError as exc:
        logger.warning("hubspot_oauth.token_exchange_failed", error=exc.error)
        return error_page(
            "Connection Failed",
            f"HubSpot reported an error completing this connection: {exc.error}. "
            "Please try again or contact support if this continues.",
            400,
            request=request,
            retry_path="/install",
        )

    await _persist_new_tenant(result)

    await record_audit("hubspot_install_completed", hub_id=result.hub_id)

    logger.info("hubspot_oauth.install_complete", hub_id=result.hub_id)
    return install_success_page(
        "HubSpot Connected",
        result.hub_id,
        "This HubSpot portal is now connected. One more step is needed to finish "
        "setup: installing the MCP Auth App, which grants read access to this "
        "portal's data.",
        request=request,
        next_path="/install/mcp-auth",
        next_label="Continue setup",
    )


async def exchange_code(code: str, code_verifier: str) -> TokenResult:
    """Exchanges an authorization code for a token pair. Credentials go in the
    POST body only, never the URL (spec requirement)."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.hubspot_app_client_id,
                "client_secret": settings.hubspot_app_client_secret,
                "redirect_uri": settings.hubspot_redirect_uri,
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

        hub_id = await _fetch_hub_id(client, access_token)

    return TokenResult(
        hub_id=hub_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )


async def refresh_token_pair(refresh_token: str) -> tuple[str, str, datetime]:
    """Refreshes an access/refresh token pair. Returns (access, refresh, expires_at)."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.hubspot_app_client_id,
                "client_secret": settings.hubspot_app_client_secret,
                "refresh_token": refresh_token,
            },
        )
        if response.status_code != 200:
            raise _parse_token_error(response)

        body = response.json()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=body["expires_in"])
        return body["access_token"], body["refresh_token"], expires_at


async def _fetch_hub_id(client: httpx.AsyncClient, access_token: str) -> str:
    response = await client.get(ACCESS_TOKEN_INFO_URL.format(token=access_token))
    if response.status_code != 200:
        raise _parse_token_error(response)
    return str(response.json()["hub_id"])


async def _persist_new_tenant(result: TokenResult) -> None:
    from .crypto import derive_tenant_key, encrypt

    key = derive_tenant_key(result.hub_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO tenants (hub_id, install_status)
                VALUES ($1, 'installed')
                ON CONFLICT (hub_id) DO UPDATE SET install_status = 'installed', updated_at = now()
                """,
                result.hub_id,
            )
            await conn.execute(
                """
                INSERT INTO tokens (hub_id, encrypted_access_token, encrypted_refresh_token, expires_at)
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
