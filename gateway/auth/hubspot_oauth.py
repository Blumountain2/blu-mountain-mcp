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


def state_ttl() -> timedelta:
    """In-flight PKCE state validity window for /install -> /callback."""
    return timedelta(minutes=settings.oauth_state_ttl_minutes)


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
    hub_domain: str | None = None


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


# Three response shapes /callback's own error paths need, differing only
# in the retry path/label and which logger event name identifies which
# failure occurred.


def missing_code_or_state_response(request: Request, retry_path: str) -> HTMLResponse:
    return error_page(
        "Something Went Wrong",
        "This link is missing required information. Please start the "
        "connection process again.",
        400,
        request=request,
        retry_path=retry_path,
    )


def expired_state_response(log_event: str, request: Request, retry_path: str) -> HTMLResponse:
    logger.warning(log_event)
    return error_page(
        "Link Expired",
        "This connection link has expired or was already used. Please "
        "start again.",
        403,
        request=request,
        retry_path=retry_path,
    )


def exchange_failed_response(
    log_event: str, exc: HubSpotOAuthError, request: Request, retry_path: str
) -> HTMLResponse:
    logger.warning(log_event, error=exc.error)
    return error_page(
        "Connection Failed",
        f"HubSpot reported an error completing this connection: {exc.error}. "
        "Please try again or contact support if this continues.",
        400,
        request=request,
        retry_path=retry_path,
    )


@router.get("/install")
async def install(portal_name: str | None = None) -> RedirectResponse:
    """Starts Flow B: redirects the client portal admin to HubSpot's authorization URL.

    portal_name is an optional human-readable name for this client (e.g.
    "Blu Mountain & Gumpper"), supplied by whoever sends the install link —
    HubSpot's API has no such field to fetch it from (confirmed: neither the
    OAuth token responses nor the dedicated account-info endpoint carry a
    company/display name, only technical fields like portalId/domain/
    timezone). Carried across the redirect round-trip via oauth_states, the
    same way code_verifier already is. A blank or whitespace-only value
    (`?portal_name=` with nothing, or all spaces) is normalized to None here
    rather than stored as an empty string — an empty string is not NULL to
    Postgres, so it would otherwise defeat both the COALESCE that protects
    an existing name from being cleared on reinstall and the COALESCE that
    falls back to hub_domain when read, making a careless blank param
    actively worse than not passing one at all."""
    portal_name = (portal_name or "").strip() or None
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(32)

    pool = await get_pool()
    await pool.execute(
        "INSERT INTO oauth_states (state, code_verifier, portal_name) VALUES ($1, $2, $3)",
        state,
        code_verifier,
        portal_name,
    )

    params = {
        "client_id": settings.hubspot_app_client_id,
        "redirect_uri": settings.hubspot_redirect_uri,
        "scope": settings.hubspot_scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if settings.hubspot_optional_scopes:
        # A separate query param from `scope`, confirmed against HubSpot's
        # own OAuth docs: a scope missing here is just dropped from the
        # grant, it doesn't fail the whole authorization the way a missing
        # `scope` entry does — see config.py's hubspot_optional_scopes.
        params["optional_scope"] = settings.hubspot_optional_scopes
    query = httpx.QueryParams(params)
    return RedirectResponse(f"{AUTHORIZE_URL}?{query}")


@router.get("/callback")
async def callback(request: Request) -> HTMLResponse:
    """Completes Flow B: validates state, exchanges the code, persists the token pair."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or not state:
        return missing_code_or_state_response(request, retry_path="/install")

    pool = await get_pool()
    row = await pool.fetchrow(
        "DELETE FROM oauth_states WHERE state = $1 AND created_at > now() - $2::interval "
        "RETURNING code_verifier, portal_name",
        state,
        state_ttl(),
    )
    if row is None:
        return expired_state_response("hubspot_oauth.state_mismatch", request, retry_path="/install")

    code_verifier = row["code_verifier"]
    portal_name = row["portal_name"]

    try:
        result = await exchange_code(code, code_verifier)
    except HubSpotOAuthError as exc:
        return exchange_failed_response("hubspot_oauth.token_exchange_failed", exc, request, retry_path="/install")

    await _persist_new_tenant(result, portal_name)

    await record_audit("hubspot_install_completed", hub_id=result.hub_id)

    logger.info("hubspot_oauth.install_complete", hub_id=result.hub_id)
    return install_success_page(
        "HubSpot Connected",
        result.hub_id,
        "This HubSpot portal is now connected. No further setup is needed — "
        "this single install grants read access to this portal's data.",
        request=request,
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

        hub_id, hub_domain = await _fetch_hub_id_and_domain(client, access_token)

    return TokenResult(
        hub_id=hub_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        hub_domain=hub_domain,
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


async def _fetch_hub_id_and_domain(
    client: httpx.AsyncClient, access_token: str
) -> tuple[str, str | None]:
    """Confirmed live: this response also carries hub_domain (HubSpot's own
    example: "hub_domain": "meowmix.com") — a real, human-recognizable
    identifier for the portal, fetched here for free since this call already
    happens on every install. HubSpot has no API for a portal's actual
    company/display name (confirmed against its account-info endpoint and
    community docs), so hub_domain is the best automatic fallback available,
    not a substitute for a manually-supplied name (see /install's
    portal_name param)."""
    response = await client.get(ACCESS_TOKEN_INFO_URL.format(token=access_token))
    if response.status_code != 200:
        raise _parse_token_error(response)
    body = response.json()
    return str(body["hub_id"]), body.get("hub_domain")


async def _persist_new_tenant(result: TokenResult, portal_name: str | None = None) -> None:
    from .crypto import derive_tenant_key, encrypt

    key = derive_tenant_key(result.hub_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO tenants (hub_id, portal_name, hub_domain, install_status)
                VALUES ($1, NULLIF(TRIM($2), ''), NULLIF(TRIM($3), ''), 'installed')
                ON CONFLICT (hub_id) DO UPDATE SET
                    install_status = 'installed',
                    portal_name = COALESCE(NULLIF(TRIM(EXCLUDED.portal_name), ''), tenants.portal_name),
                    hub_domain = COALESCE(NULLIF(TRIM(EXCLUDED.hub_domain), ''), tenants.hub_domain),
                    updated_at = now()
                """,
                result.hub_id,
                portal_name,
                result.hub_domain,
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
