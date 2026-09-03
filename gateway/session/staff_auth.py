"""
Direct Google Workspace and Microsoft 365 JWT verification.

Not wired into main.py: no planning document identifies a consumer for this
distinct from what the live session already does (see design.md's decision
log in the implement-hubspot-mcp-server change). Kept, unhooked, in case a
future non-MCP consumer (e.g. a web dashboard) needs a plain bearer-token
verifier. Verifies a JWT issued directly by Google or Microsoft against
that provider's own JWKS endpoint. Never used for client-facing access.
"""

from typing import Any, Dict

import jwt
from jwt import PyJWKClient
from fastapi import HTTPException
import structlog

from config import settings

logger = structlog.get_logger()


def _verify_with_jwks(token: str, jwks_url: str, audience: str | None, log_event: str) -> Dict[str, Any]:
    """Shared by both providers below — fetch the signing key for this
    token from `jwks_url`, decode and verify it, and raise a uniform 401
    on any failure. Only the JWKS endpoint, audience, and log event name
    differ per provider."""
    jwks_client = PyJWKClient(jwks_url)
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(token, signing_key.key, algorithms=["RS256"], audience=audience)
    except jwt.PyJWTError as e:
        logger.error(log_event, error=str(e))
        raise HTTPException(401, "Invalid token") from e


class StaffDirectAuthenticator:
    """Verifies staff/owner JWTs issued directly by Google Workspace or Microsoft 365."""

    def __init__(self):
        self.google_client_id = settings.google_client_id
        self.google_hosted_domain = settings.google_hosted_domain
        self.microsoft_client_id = settings.microsoft_client_id
        self.microsoft_tenant_id = settings.microsoft_tenant_id

    async def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify a staff JWT, routing to the correct provider by issuer."""
        try:
            unverified_claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.InvalidTokenError as e:
            logger.error("staff_auth.malformed_token", error=str(e))
            raise HTTPException(401, "Malformed token")

        issuer = unverified_claims.get("iss", "")

        if "accounts.google.com" in issuer:
            return await self._verify_google_token(token)
        if "login.microsoftonline.com" in issuer:
            return await self._verify_microsoft_token(token)

        logger.error("staff_auth.unknown_issuer", issuer=issuer)
        raise HTTPException(401, "Unknown identity provider")

    async def _verify_google_token(self, token: str) -> Dict[str, Any]:
        """Verify a Google Workspace JWT and enforce the hosted-domain restriction."""
        claims = _verify_with_jwks(
            token,
            "https://www.googleapis.com/oauth2/v3/certs",
            self.google_client_id,
            "staff_auth.google_invalid",
        )

        if self.google_hosted_domain and claims.get("hd") != self.google_hosted_domain:
            logger.error("staff_auth.google_domain_rejected", hd=claims.get("hd"))
            raise HTTPException(401, "Google account is outside the permitted domain")

        return claims

    async def _verify_microsoft_token(self, token: str) -> Dict[str, Any]:
        """Verify a Microsoft 365 JWT."""
        jwks_url = f"https://login.microsoftonline.com/{self.microsoft_tenant_id}/discovery/v2.0/keys"
        return _verify_with_jwks(token, jwks_url, self.microsoft_client_id, "staff_auth.microsoft_invalid")
