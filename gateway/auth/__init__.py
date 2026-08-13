"""Public surface of the auth subsystem: HubSpot OAuth v3 + PKCE
install/callback for both the Public App (Flow B) and the MCP Auth App, the
per-tenant token vaults, tenant-key encryption, and the shared audit log /
rate-limit primitives other subsystems depend on."""

from .crypto import decrypt, derive_tenant_key, encrypt
from .hubspot_oauth import router as hubspot_oauth_router
from .mcp_auth import router as mcp_auth_router
from .security import check_rate_limit, purge_expired_audit_log, record_audit
from .token_vault import InMemoryAccessTokenCache, TokenVault, get_installed_hub_ids, mcp_vault, vault
from .token_vault import router as token_vault_router

__all__ = [
    "decrypt",
    "derive_tenant_key",
    "encrypt",
    "hubspot_oauth_router",
    "mcp_auth_router",
    "check_rate_limit",
    "purge_expired_audit_log",
    "record_audit",
    "InMemoryAccessTokenCache",
    "TokenVault",
    "get_installed_hub_ids",
    "vault",
    "mcp_vault",
    "token_vault_router",
]
