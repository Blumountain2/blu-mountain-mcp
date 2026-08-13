"""
Direct Google Workspace and Microsoft 365 JWT verification.

Not wired into main.py: no planning document identifies a consumer for this
distinct from what the live session already does (see design.md's decision
log in the implement-hubspot-mcp-server change). Kept, unhooked, in case a
future non-MCP consumer (e.g. a web dashboard) needs a plain bearer-token
verifier. Verifies a JWT issued directly by Google or Microsoft against
that provider's own JWKS endpoint. Never used for client-facing access.
"""

import os
from typing import Any, Dict

import jwt
from jwt import PyJWKClient
from fastapi import HTTPException
import structlog

logger = structlog.get_logger()


class StaffDirectAuthenticator:
    """Verifies staff/owner JWTs issued directly by Google Workspace or Microsoft 365."""

    def __init__(self):
        self.google_client_id = os.getenv("GOOGLE_CLIENT_ID")
        self.google_hosted_domain = os.getenv("GOOGLE_HOSTED_DOMAIN")
        self.microsoft_client_id = os.getenv("MICROSOFT_CLIENT_ID")
        self.microsoft_tenant_id = os.getenv("MICROSOFT_TENANT_ID", "common")

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
        jwks_client = PyJWKClient("https://www.googleapis.com/oauth2/v3/certs")

        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.google_client_id,
            )
        except jwt.PyJWTError as e:
            logger.error("staff_auth.google_invalid", error=str(e))
            raise HTTPException(401, "Invalid Google token")

        if self.google_hosted_domain and claims.get("hd") != self.google_hosted_domain:
            logger.error("staff_auth.google_domain_rejected", hd=claims.get("hd"))
            raise HTTPException(401, "Google account is outside the permitted domain")

        return claims

    async def _verify_microsoft_token(self, token: str) -> Dict[str, Any]:
        """Verify a Microsoft 365 JWT."""
        jwks_url = f"https://login.microsoftonline.com/{self.microsoft_tenant_id}/discovery/v2.0/keys"
        jwks_client = PyJWKClient(jwks_url)

        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.microsoft_client_id,
            )
        except jwt.PyJWTError as e:
            logger.error("staff_auth.microsoft_invalid", error=str(e))
            raise HTTPException(401, "Invalid Microsoft token")

        return claims
