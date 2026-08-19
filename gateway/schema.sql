-- Postgres schema for the HubSpot MCP Server.
-- Single instance, no Redis: token vault, cache backing, advisory locks,
-- rate limiting, audit log, and staff-to-tenant permissions all live here.

CREATE TABLE IF NOT EXISTS tenants (
    hub_id TEXT PRIMARY KEY,
    portal_name TEXT,
    hub_domain TEXT,
    install_status TEXT NOT NULL DEFAULT 'installed',
    installed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- hub_domain didn't exist when this table was first created — this file has
-- no separate migration tool, so an idempotent ALTER right after the CREATE
-- is how an already-provisioned database (real vaulted tenant tokens, not
-- droppable) picks up a new column; a fresh database just gets it as a
-- no-op. portal_name is the human-curated name (set only via /install's
-- optional query param, never auto-overwritten); hub_domain is HubSpot's own
-- domain for the portal, auto-captured from the OAuth access-token-info
-- response on every install/reinstall. Readers should use
-- COALESCE(portal_name, hub_domain, hub_id), never hub_domain alone.
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS hub_domain TEXT;

CREATE TABLE IF NOT EXISTS tokens (
    hub_id TEXT PRIMARY KEY REFERENCES tenants(hub_id) ON DELETE CASCADE,
    encrypted_access_token TEXT NOT NULL,
    encrypted_refresh_token TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    last_refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Separate vault for the MCP Auth App's token (spec Section 4.1) — a
-- distinct credential from `tokens` above, since HubSpot's remote MCP
-- endpoint (mcp.hubspot.com) does not accept the Public App's CRM-scoped
-- token. Same shape, same per-tenant keying, deliberately not merged into
-- `tokens` so each app's token lifecycle stays independently refreshable.
CREATE TABLE IF NOT EXISTS mcp_tokens (
    hub_id TEXT PRIMARY KEY REFERENCES tenants(hub_id) ON DELETE CASCADE,
    encrypted_access_token TEXT NOT NULL,
    encrypted_refresh_token TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    last_refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tracks in-flight PKCE installs between /install and /callback.
CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    code_verifier TEXT NOT NULL,
    portal_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- portal_name carries /install's optional ?portal_name= query param across
-- the redirect round-trip to /callback, the same way code_verifier already
-- does — see the ALTER note on tenants above for why this ALTER exists too.
ALTER TABLE oauth_states ADD COLUMN IF NOT EXISTS portal_name TEXT;

-- Per-tenant token-bucket rate limiting (SC-7).
CREATE TABLE IF NOT EXISTS rate_limit_buckets (
    hub_id TEXT PRIMARY KEY,
    tokens NUMERIC NOT NULL,
    last_refill TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-tenant audit log, minimum 60-day retention (SC-6). staff_identity is
-- NULL for scheduled-job activity, populated for live session access.
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    hub_id TEXT,
    staff_identity TEXT,
    event_type TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_audit_log_occurred_at ON audit_log (occurred_at);
CREATE INDEX IF NOT EXISTS idx_audit_log_hub_id ON audit_log (hub_id);

-- Superseded by staff_tenant_restrictions below (allow-list -> deny-list,
-- see design.md's decision log). Dropped explicitly, not just left behind,
-- since CREATE TABLE IF NOT EXISTS alone would never remove it from any
-- environment that already applied the old schema, and no real client's
-- access data has ever depended on this table's old allow-list rows.
DROP TABLE IF EXISTS staff_tenant_permissions;

-- Default-open staff tenant access for the live session (AF-3): any staff
-- member who signs in successfully has access to every installed tenant
-- UNLESS a row here explicitly restricts them from a specific one. This is
-- a deny-list, not an allow-list — presence of a row means "blocked from
-- this tenant," not "granted access to it." hub_id references tenants so a
-- mistyped hub_id (no admin UI exists; this is hand-typed SQL) fails loudly
-- at insert time instead of silently becoming a permanent no-op restriction
-- that never matches anything in the installed set. No ON DELETE CASCADE
-- needed: tenants rows are never deleted, only marked uninstalled, and a
-- restriction on an uninstalled tenant is still meaningful.
CREATE TABLE IF NOT EXISTS staff_tenant_restrictions (
    staff_identity TEXT NOT NULL,
    hub_id TEXT NOT NULL REFERENCES tenants(hub_id),
    PRIMARY KEY (staff_identity, hub_id)
);

-- Tracks each live session's selected tenant, required whenever a staff
-- member has more than one permitted tenant (AF-3).
CREATE TABLE IF NOT EXISTS live_session_selection (
    session_id TEXT PRIMARY KEY,
    staff_identity TEXT NOT NULL,
    selected_hub_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Maps a HubSpot company/deal ID to the tenant it belongs to, populated as
-- objects are staged. Used to resolve which tenant a Sybill transcript
-- belongs to via its crmInfo.accountId/opportunityId, since Sybill's
-- payload carries no hub_id of its own. object_id is NOT globally unique
-- across portals by itself, hence the composite key: a given (object_type,
-- object_id) pair is only trusted for tenant resolution if it maps to
-- exactly one hub_id.
CREATE TABLE IF NOT EXISTS hubspot_object_index (
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    hub_id TEXT NOT NULL,
    PRIMARY KEY (object_type, object_id, hub_id)
);

CREATE INDEX IF NOT EXISTS idx_hubspot_object_index_lookup
    ON hubspot_object_index (object_type, object_id);
