"""Centralized environment configuration for the HubSpot MCP Server."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The Public App (Flow B): one shared credential, installed once per
    # client portal, used for the standard CRM OAuth v3 flow.
    hubspot_app_client_id: str = ""
    hubspot_app_client_secret: str = ""
    hubspot_redirect_uri: str = "http://localhost:8888/callback"
    hubspot_scopes: str = (
        "crm.objects.contacts.read crm.objects.companies.read "
        "crm.objects.deals.read tickets.read"
    )
    # Scopes requested via HubSpot's separate `optional_scope` authorize
    # param (auth/hubspot_oauth.py's install()): unlike `scope`, a portal
    # lacking one of these (e.g. no Marketing Hub Professional+ for
    # marketing.campaigns.read) just has it omitted from the grant rather
    # than failing the whole install — confirmed live this project's own
    # HUBSPOT_SCOPES grant of marketing.campaigns.read as *required* hard-
    # failed real installs with "your account lacks access to the required
    # scopes" on both test portals. Empty by default; not every deployment
    # needs an optional-scope split.
    hubspot_optional_scopes: str = ""

    fastmcp_google_client_id: str = ""
    fastmcp_google_client_secret: str = ""
    # Documentation-only: what to register as the redirect URI on the
    # Google Cloud OAuth client itself. Not read by any code here —
    # FastMCP's GoogleProvider derives the actual redirect path from
    # fastmcp_base_url below, it takes no separate full-URI parameter.
    fastmcp_oauth_redirect_uri: str = "http://localhost:8888/mcp/auth/callback"
    fastmcp_base_url: str = "http://localhost:8888/mcp"
    fastmcp_allowed_google_domains: str = ""
    fastmcp_access_token_ttl_minutes: int = 30

    google_client_id: str = ""
    google_hosted_domain: str = ""
    microsoft_client_id: str = ""
    # "common" is Microsoft's own multi-tenant discovery endpoint alias,
    # not a placeholder — session/staff_auth.py's direct JWT verification
    # has always defaulted to it when unset.
    microsoft_tenant_id: str = "common"

    database_url: str = "postgresql://mcp:change-me@localhost:5432/mcp"

    oauth_state_ttl_minutes: int = 10

    app_encryption_key: str = ""

    rate_limit_per_minute: int = 100
    audit_retention_days: int = 60

    # Identification-only: whose account AIRTABLE_API_KEY belongs to, not
    # a credential itself. Not read by any code — airtable_api_key alone
    # is what sync/airtable_staging.py's _api() actually authenticates with.
    airtable_service_account: str = ""
    airtable_api_key: str = ""
    airtable_base_id: str = ""
    sync_interval_minutes: int = 60

    sybill_webhook: str = ""

    # Vertical pull agent (openspec/changes/analysis-model-templates,
    # Section 8): a Claude API tool-use agent, one config per vertical,
    # that decides which of the existing allowlisted HubSpot pull methods
    # to call. Data-gathering only, never analysis — see design.md's
    # Non-Negotiables. No fine-tuning/training involved; this is a plain
    # API credential, not a per-client one.
    anthropic_api_key: str = ""

    # Debug HubSpot data API (gateway/debug_api.py): a plain HTTP surface for
    # pulling a real installed tenant's HubSpot data directly, for manual
    # testing via Postman rather than through the MCP protocol. This is a
    # real, if narrow, expansion of this service's HTTP attack surface onto
    # live tenant data, so it's gated shut by default: every request needs
    # X-Debug-Api-Key to match this value exactly, and an empty value here
    # (the default) makes every request 401 unconditionally — fails closed
    # when unconfigured, the same posture as an empty
    # FASTMCP_ALLOWED_GOOGLE_DOMAINS. Every successful pull is still
    # recorded in audit_log, same as the live session's own reads.
    debug_api_key: str = ""

    @property
    def allowed_google_domains_list(self) -> list[str]:
        """Lowercased, since it's compared against the token's hd claim
        (also lowercased at the point of extraction) — domains are
        case-insensitive in reality, so a casing mismatch here should never
        be able to reject a legitimate staff member."""
        return [d.strip().lower() for d in self.fastmcp_allowed_google_domains.split(",") if d.strip()]


settings = Settings()
