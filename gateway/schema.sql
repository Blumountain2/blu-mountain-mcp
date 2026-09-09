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

-- tenants.vertical (task 7.2, openspec/changes/analysis-model-templates)
-- held a staff-set vertical for the profiling/onboarding pipeline below —
-- dropped alongside it (see the note further down): a client's vertical
-- is now fixed by which vertical class its agent subclasses
-- (gateway/frameworks/agents/clients/*.py), a git-tracked decision, not a
-- live-updatable database value.
ALTER TABLE tenants DROP COLUMN IF EXISTS vertical;

CREATE TABLE IF NOT EXISTS tokens (
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

-- The MCP Auth App's separate token vault (spec Section 4.1), superseded
-- by the REST pivot (openspec/changes/hubspot-rest-api-pivot, Section 7
-- cutover): HubSpotDataPullClient now reads HubSpot's plain REST API
-- using the Public App's own `tokens` row, so this second credential and
-- its vault are no longer needed. Dropped explicitly, applied idempotently
-- on every startup like staff_tenant_permissions above — the real vaulted
-- MCP Auth tokens this held were already dead by the time this ran (the
-- MCP Auth App's own registration in HubSpot was deleted directly).
DROP TABLE IF EXISTS mcp_tokens;

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
-- belongs to via its data.crm.id (see webhooks/sybill.py's module
-- docstring for the real, confirmed-live payload shape), since Sybill's
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

-- Stores Blu Mountain's own-authored analysis content (vertical frameworks,
-- the vertical-agnostic operational skill, and the runtime prompt) — see
-- openspec/changes/analysis-model-templates/. This project ingests and
-- serves this content, it does not author it. Append-only by convention:
-- a new version is always a new row, never an UPDATE, so an
-- already-produced tenant onboarding profile that references an older
-- version can never be silently altered by a later ingestion
-- (analysis-template-schema's versioning requirement). content_type is
-- 'vertical_framework' (name = e.g. 'saas', 'plg', 'marketplace',
-- 'ecommerce', 'services-project', 'transactional'), 'skill', or 'prompt'
-- — the latter two have exactly one real name each today
-- ('account-diagnostic-skill', 'weekly-diagnostic-prompt') but the schema
-- doesn't assume that stays true.
CREATE TABLE IF NOT EXISTS analysis_content (
    id SERIAL PRIMARY KEY,
    content_type TEXT NOT NULL,
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    source_path TEXT,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (content_type, name, version)
);

CREATE INDEX IF NOT EXISTS idx_analysis_content_lookup
    ON analysis_content (content_type, name, version DESC);

-- tenant_onboarding_profiles/tenant_onboarding_profile_fields (task 3,
-- specs/tenant-template-instantiation/spec.md): formerly a lightweight,
-- named, per-tenant record of which fields were confirmed relevant for a
-- tenant's analysis. Dropped for the same reason as vertical_agent_templates/
-- client_agent_instances below, and discovered the same way: a real
-- caller audit (2026-09-08) confirmed produce_onboarding_profile/
-- get_profile_for_tenant/get_latest_profile_for_tenant/review_field had no
-- production caller left after the class-based agent migration —
-- CONFIRMED_FIELDS (gateway/frameworks/agents/clients/*.py) replaced this
-- persisted, database-driven curation record with real, git-tracked code,
-- the same "codebase, not Postgres rows" direction this whole area of the
-- project has now taken twice. gateway/scripts/generate_confirmed_fields.py
-- reads the same underlying live HubSpot data (frameworks.profiling.
-- profile_tenant_fields) to propose CONFIRMED_FIELDS values directly,
-- without a persistence layer in between. Dropped explicitly, applied
-- idempotently on every startup like the tables below — neither real row's
-- worth of data (hub_id 148997330, 149094230) had anything beyond
-- needs_review fields, already re-derivable live from HubSpot at any time.
-- tenant_onboarding_profile_fields dropped first since it FK-references
-- tenant_onboarding_profiles.
DROP TABLE IF EXISTS tenant_onboarding_profile_fields;
DROP TABLE IF EXISTS tenant_onboarding_profiles;

-- vertical_agent_templates/client_agent_instances (openspec/changes/
-- separate-vertical-client-agents): persisted vertical/client agent
-- configuration as database rows, specifically so it could be edited
-- without a code deploy. Superseded by a further, deliberate reversal
-- (openspec/changes/client-vertical-agent-classes, direct leadership
-- directive — see that change's design.md for the full history of this
-- recurring decision): a vertical's and a client's agent behavior now
-- lives in real, version-controlled Python classes under
-- gateway/frameworks/agents/ instead. Dropped explicitly, applied
-- idempotently on every startup like mcp_tokens/staff_tenant_permissions
-- above — the two real rows this ever held (hub_id 148997330, 149094230)
-- had zero confirmed-relevant fields and empty template additions, so
-- nothing of substance was lost; both were hand-migrated into real
-- client files before this drop landed. client_agent_instances dropped
-- first since it FK-references vertical_agent_templates.
DROP TABLE IF EXISTS client_agent_instances;
DROP TABLE IF EXISTS vertical_agent_templates;
