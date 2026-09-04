"""Public surface of the auth subsystem: HubSpot OAuth v3 + PKCE
install/callback for the Public App (Flow B), the per-tenant token vault,
tenant-key encryption, and the shared audit log / rate-limit primitives
other subsystems depend on.

The MCP Auth App's own OAuth flow and token vault (spec Section 4.1,
mcp_auth.py/mcp_vault) have been removed entirely
(openspec/changes/hubspot-rest-api-pivot, Section 7 cutover) —
HubSpotDataPullClient reads HubSpot's plain REST API using the Public
App's own token now, so that second install step and credential no longer
exist. The real vaulted MCP Auth App tokens are gone (the app registration
itself was deleted directly in HubSpot), and the mcp_tokens table is
dropped in schema.sql."""

from .crypto import decrypt, derive_tenant_key, encrypt
from .hubspot_oauth import router as hubspot_oauth_router
from .security import check_rate_limit, purge_expired_audit_log, record_audit, record_audit_best_effort
from .token_vault import (
    TENANT_DISPLAY_NAME_SQL,
    InMemoryAccessTokenCache,
    PostgresAccessTokenCache,
    TokenVault,
    get_installed_hub_ids,
    vault,
)
from .token_vault import router as token_vault_router

__all__ = [
    "decrypt",
    "derive_tenant_key",
    "encrypt",
    "hubspot_oauth_router",
    "check_rate_limit",
    "purge_expired_audit_log",
    "record_audit",
    "record_audit_best_effort",
    "InMemoryAccessTokenCache",
    "PostgresAccessTokenCache",
    "TokenVault",
    "TENANT_DISPLAY_NAME_SQL",
    "get_installed_hub_ids",
    "vault",
    "token_vault_router",
]
