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

-- A tenant's known vertical (task 7.2, openspec/changes/analysis-model-templates):
-- staff-set, never inferred automatically. Distinct from
-- tenant_onboarding_profiles.vertical, which is a point-in-time snapshot
-- taken when a profile was produced; this column is the current,
-- live-updatable value a new profile or pull-agent run reads at call time.
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS vertical TEXT;

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

-- A tenant onboarding profile (task 3, specs/tenant-template-instantiation
-- /spec.md): a lightweight, named, per-tenant record of which fields are
-- confirmed relevant for that tenant's analysis. Deliberately NOT a copy
-- of a framework/skill/prompt — those stay shared and unmodified in
-- analysis_content above; this is only the runtime parameter meant to
-- accompany one at invocation time. `name` is a snapshot of the tenant's
-- effective display name (portal_name -> hub_domain -> hub_id, same
-- resolution already used for the live session) AT PRODUCTION TIME, not
-- a live join — a profile is a point-in-time artifact, matching
-- analysis_content's own versioned-snapshot philosophy, so it doesn't
-- silently change if the tenant's name changes later. `vertical` may be
-- NULL if not yet known for this tenant.
CREATE TABLE IF NOT EXISTS tenant_onboarding_profiles (
    id SERIAL PRIMARY KEY,
    hub_id TEXT NOT NULL REFERENCES tenants(hub_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    vertical TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenant_onboarding_profiles_hub_id
    ON tenant_onboarding_profiles (hub_id);

-- One row per populated field a profile considered. Only populated
-- fields are stored at all — an unpopulated field has nothing to analyze
-- regardless of framework guidance, so it's simply never a candidate.
-- status is 'confirmed_relevant' (auto-confirmed at production time if
-- the tenant's framework already has explicit guidance for this
-- property — either trust_by_default or unreliable_by_default, both are
-- the framework actively discussing this field, not silence about it),
-- 'confirmed_irrelevant', or 'needs_review' (no framework guidance
-- existed for this field at production time — a human must decide). A
-- profile is "final" only once no field is left at 'needs_review'
-- (frameworks.onboarding.OnboardingProfile.is_final).
CREATE TABLE IF NOT EXISTS tenant_onboarding_profile_fields (
    profile_id INTEGER NOT NULL REFERENCES tenant_onboarding_profiles(id) ON DELETE CASCADE,
    object_type TEXT NOT NULL,
    property_name TEXT NOT NULL,
    status TEXT NOT NULL,
    framework_guidance TEXT,
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    PRIMARY KEY (profile_id, object_type, property_name)
);

-- openspec/changes/separate-vertical-client-agents: a vertical agent
-- template is this project's OWN configuration layered around a vertical
-- framework's raw text (analysis_content above) — never a copy of that
-- framework itself. Versioned and append-only, same pattern as
-- analysis_content, so an already-produced client_agent_instances row
-- keeps referencing the exact template version it was built from even
-- after a vertical's template is later updated. Deliberately a separate
-- table from analysis_content: that table promises shared, Blu-Mountain-
-- authored, unmodified content; this one is this project's own tool/model
-- configuration, a genuinely different concern.
CREATE TABLE IF NOT EXISTS vertical_agent_templates (
    id SERIAL PRIMARY KEY,
    vertical TEXT NOT NULL,
    version INTEGER NOT NULL,
    system_prompt_additions TEXT NOT NULL,
    tool_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vertical, version)
);

CREATE INDEX IF NOT EXISTS idx_vertical_agent_templates_lookup
    ON vertical_agent_templates (vertical, version DESC);

-- A client agent instance: the per-client artifact this change adds,
-- superseding the prior "one shared agent config per vertical, no
-- per-client persistence" design (see
-- openspec/changes/analysis-model-templates/design.md's Non-Negotiable
-- #6, explicitly superseded by openspec/changes/separate-vertical-client
-- -agents/design.md). One row per client, versioned and never mutated in
-- place — a new instance is always a new row, so an in-flight run keeps
-- using the version it started with. vertical_template_id is a real FK
-- (not just a copied vertical name) so a client instance is always
-- traceable to the exact vertical template version it was built from.
-- injected_documentation is a rendered snapshot (that client's
-- confirmed-relevant onboarding-profile fields, custom-field guidance,
-- and any client-specific notes) taken at production time, matching this
-- project's existing versioned-snapshot philosophy (tenant_onboarding_
-- profiles.name works the same way) — not a live join that could
-- silently change out from under an already-running agent.
CREATE TABLE IF NOT EXISTS client_agent_instances (
    id SERIAL PRIMARY KEY,
    hub_id TEXT NOT NULL REFERENCES tenants(hub_id) ON DELETE CASCADE,
    vertical_template_id INTEGER NOT NULL REFERENCES vertical_agent_templates(id),
    version INTEGER NOT NULL,
    injected_documentation TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Matches vertical_agent_templates' own UNIQUE (vertical, version) and
    -- analysis_content's UNIQUE (content_type, name, version) — this table
    -- was missing the equivalent backstop. next_version()'s
    -- SELECT MAX(version)+1 has no locking of its own; without this
    -- constraint, two concurrent first-time produce_client_agent_instance
    -- calls for the same not-yet-onboarded tenant could both compute
    -- version=1 and both insert successfully, leaving two ambiguous rows
    -- get_latest_client_agent_instance's ORDER BY version DESC LIMIT 1
    -- (no tiebreaker) would then resolve nondeterministically.
    UNIQUE (hub_id, version)
);

CREATE INDEX IF NOT EXISTS idx_client_agent_instances_hub_id
    ON client_agent_instances (hub_id, created_at DESC);

-- Retrofits the UNIQUE (hub_id, version) constraint above onto any
-- database where client_agent_instances already existed before this
-- constraint was added (CREATE TABLE IF NOT EXISTS only applies it to a
-- brand-new table). Postgres has no ADD CONSTRAINT IF NOT EXISTS, so this
-- checks pg_constraint directly rather than relying on exception class
-- matching — confirmed live that a duplicate constraint name here raises
-- DuplicateTableError (the implicit backing index collides), not the
-- duplicate_object condition an EXCEPTION WHEN clause would need.
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'client_agent_instances_hub_id_version_key'
    ) THEN
        ALTER TABLE client_agent_instances
            ADD CONSTRAINT client_agent_instances_hub_id_version_key UNIQUE (hub_id, version);
    END IF;
END $$;
