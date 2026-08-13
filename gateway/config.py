"""Centralized environment configuration for the HubSpot MCP Server."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gateway_mode: str = "development"
    log_level: str = "info"
    gateway_port: int = 8888

    # The Public App (Flow B): one shared credential, installed once per
    # client portal, used for the standard CRM OAuth v3 flow.
    hubspot_app_client_id: str = ""
    hubspot_app_client_secret: str = ""
    hubspot_redirect_uri: str = "http://localhost:8888/callback"
    hubspot_scopes: str = (
        "crm.objects.contacts.read crm.objects.companies.read "
        "crm.objects.deals.read tickets.read"
    )

    # The MCP Auth App (spec Section 4.1): a separate shared credential,
    # also installed once per client portal, specifically for connecting to
    # HubSpot's remote MCP endpoint (mcp.hubspot.com) — that endpoint does
    # not accept the Public App's own CRM-scoped token.
    hubspot_mcp_client_id: str = ""
    hubspot_mcp_client_secret: str = ""
    hubspot_mcp_redirect_uri: str = "http://localhost:8888/callback/mcp-auth"

    fastmcp_google_client_id: str = ""
    fastmcp_google_client_secret: str = ""
    fastmcp_oauth_redirect_uri: str = "http://localhost:8888/mcp/auth/callback"
    fastmcp_base_url: str = "http://localhost:8888/mcp"
    fastmcp_allowed_google_domains: str = ""
    fastmcp_access_token_ttl_minutes: int = 30

    google_client_id: str = ""
    google_hosted_domain: str = ""
    microsoft_client_id: str = ""
    microsoft_tenant_id: str = ""

    database_url: str = "postgresql://mcp:change-me@localhost:5432/mcp"

    app_encryption_key: str = ""

    rate_limit_per_minute: int = 100
    audit_retention_days: int = 60

    airtable_service_account: str = ""
    airtable_api_key: str = ""
    airtable_base_id: str = ""
    sync_interval_minutes: int = 60

    sybill_webhook: str = ""

    @property
    def allowed_google_domains_list(self) -> list[str]:
        """Lowercased, since it's compared against the token's hd claim
        (also lowercased at the point of extraction) — domains are
        case-insensitive in reality, so a casing mismatch here should never
        be able to reject a legitimate staff member."""
        return [d.strip().lower() for d in self.fastmcp_allowed_google_domains.split(",") if d.strip()]


settings = Settings()
