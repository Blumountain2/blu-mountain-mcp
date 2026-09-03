# Database Reference

The full Postgres schema for this service (`gateway/schema.sql`), table by
table: every column, its type, and what it's actually for — cross-checked
against the code that reads and writes it, not just the column names. One
Postgres instance backs everything: the token vault, the access-token cache,
advisory locks, rate limiting, the audit log, and staff tenant access. No
Redis, no second datastore.

`hub_id` (HubSpot's portal identifier) is the tenant key threaded through
almost every table here — it's how every piece of this system scopes itself
to exactly one client.

## `tenants`

One row per connected client portal. The canonical list of which clients
exist and whether they're currently installed.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `hub_id` | `TEXT` (PK) | HubSpot's portal identifier. Primary tenant key referenced by `tokens`, `rate_limit_buckets`, `audit_log`, `staff_tenant_restrictions`, `hubspot_object_index`, `tenant_onboarding_profiles`. |
| `portal_name` | `TEXT` | Human-curated display name, set only via `/install`'s optional `?portal_name=` query param (round-tripped through `oauth_states.portal_name`) — never auto-overwritten. |
| `hub_domain` | `TEXT` | HubSpot's own domain for the portal, auto-captured from the OAuth access-token-info response on every install/reinstall. Readers should use `COALESCE(portal_name, hub_domain, hub_id)`, never `hub_domain` alone — this is the resolution order both the live session and `frameworks/onboarding.py::_effective_tenant_name` use. |
| `vertical` | `TEXT` | The tenant's known vertical framework (e.g. `saas`, `plg`), staff-set via `frameworks/vertical.py::set_tenant_vertical` — **never inferred automatically**. `NULL` until a human sets it. `frameworks/onboarding.py::produce_onboarding_profile` reads this as its default when no vertical is passed explicitly; a profile produced with no vertical (and not explicitly `allow_unqualified=True`) is refused. Distinct from `tenant_onboarding_profiles.vertical`, which is a point-in-time snapshot taken when a profile was produced — this column is the current, live-updatable value. |
| `install_status` | `TEXT` | `'installed'` (default, set on every successful `/callback`) or `'uninstalled'` (set by `auth/token_vault.py` when HubSpot's uninstall webhook fires). This is the flag that determines which tenants the scheduled sync (`sync/airtable_staging.py`) and the live session's default-open access (`session/live_session.py::_permitted_tenants`) both treat as "active" — an uninstalled tenant's row is kept, not deleted, but excluded from both. |
| `installed_at` | `TIMESTAMPTZ` | Set once at first insert, never updated on re-install. |
| `updated_at` | `TIMESTAMPTZ` | Bumped on every `install_status` or `vertical` change. |

Row lifecycle: created on `/callback` (`auth/hubspot_oauth.py::_persist_new_tenant`), `ON CONFLICT (hub_id) DO UPDATE` if the same portal re-installs. Never deleted by application code.

## `tokens`

The encrypted token vault. Exactly one row per tenant, one-to-one with `tenants`.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `hub_id` | `TEXT` (PK, `REFERENCES tenants(hub_id) ON DELETE CASCADE`) | |
| `encrypted_access_token` | `TEXT` | AES-256 encrypted (via `cryptography.Fernet`), key derived per-tenant from `APP_ENCRYPTION_KEY` through HKDF using `hub_id` as context (`auth/crypto.py`). Never stored, logged, or returned in plaintext outside the vault's own decrypt call. |
| `encrypted_refresh_token` | `TEXT` | Same encryption scheme as the access token. This is the one HubSpot considers long-lived; never placed in any cache, per the spec's SC-1/FR-5. |
| `expires_at` | `TIMESTAMPTZ` | The access token's real expiry as reported by HubSpot. Checked against a 5-minute buffer (`auth/token_vault.py`) to decide whether to proactively refresh before serving it. |
| `last_refreshed_at` | `TIMESTAMPTZ` | Updated every time `refresh_token_pair` succeeds. Informational — nothing currently reads it for logic, only for audit-adjacent visibility. |

Refreshes are serialized per tenant via `pg_advisory_xact_lock(hashtext(hub_id))` (see "Locking" below), so two instances/workers can never race to refresh the same tenant simultaneously — this table itself has no lock column; the lock is a separate Postgres primitive, not vault state.

Read by `sync/hubspot_client.py::HubSpotDataPullClient` — since the REST pivot (`openspec/changes/hubspot-rest-api-pivot`), this is the only HubSpot credential in the system; it's used directly against `api.hubapi.com`.

## `mcp_tokens` (removed)

Dropped (`DROP TABLE IF EXISTS mcp_tokens;` in `schema.sql`, applied idempotently on every startup) as part of the REST pivot's cutover (`openspec/changes/hubspot-rest-api-pivot`, 2026-09-02). Formerly a second token vault, same shape as `tokens`, for the MCP Auth App (spec Section 4.1) — a separate credential HubSpot's remote MCP endpoint (`mcp.hubspot.com`) required, since it didn't accept the Public App's own token. `HubSpotDataPullClient` now reads `api.hubapi.com` directly with the Public App's token instead, so this second credential and its vault are no longer needed. The real vaulted MCP Auth tokens this held were already dead by the time the drop ran — the MCP Auth App's registration itself was deleted directly in HubSpot's developer account, not just this table.

`TokenVault` (`auth/token_vault.py`) stays parameterized by `table_name`/`refresh_fn` even though only one instance (`vault`) exists now — real, testable flexibility kept from when this table's second instance (`mcp_vault`) also existed, not speculative scaffolding.

## `oauth_states`

Short-lived, in-flight PKCE state for Flow B, between `/install` and `/callback`.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `state` | `TEXT` (PK) | Random `secrets.token_urlsafe(32)` value, round-tripped through HubSpot's authorize URL and back. |
| `code_verifier` | `TEXT` | The PKCE verifier generated alongside the state; retrieved and deleted together on a valid `/callback`. |
| `portal_name` | `TEXT` | Carries `/install`'s optional `?portal_name=` query param across the redirect round-trip, the same way `code_verifier` does; written into `tenants.portal_name` on a successful `/callback`. |
| `created_at` | `TIMESTAMPTZ` | Used to enforce the 10-minute validity window (`created_at > now() - interval '10 minutes'`) — a state older than that is treated as expired even if never explicitly deleted. |

Row lifecycle: inserted on `/install`, deleted on a **successful** `/callback` (the delete and the validity check happen in the same `DELETE ... RETURNING` statement). **A state that's never completed — the admin abandons the flow, closes the tab — is never deleted.** It's functionally expired after 10 minutes (the `created_at` check rejects it), but the row itself stays forever; there's no reaper job. Harmless at current volume (small rows, no sensitive data beyond a single-use verifier), but worth knowing if this table's row count is ever audited.

## `rate_limit_buckets`

Per-tenant token-bucket rate limiting (SC-7), one row per tenant that has made at least one request.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `hub_id` | `TEXT` (PK) | Not a foreign key to `tenants` — a bucket is created lazily on first use, independent of the tenant row's own lifecycle. |
| `tokens` | `NUMERIC` | Current bucket level. Capacity and refill rate are both derived from `RATE_LIMIT_PER_MINUTE` (`auth/security.py::check_rate_limit`): `capacity = RATE_LIMIT_PER_MINUTE`, `refill_per_second = capacity / 60`. Not separate columns — recomputed from config on every check, not stored. |
| `last_refill` | `TIMESTAMPTZ` | The instant `tokens` was last computed; elapsed time since this is what the next check uses to top the bucket back up before charging one token. |

Read-modify-write happens inside `SELECT ... FOR UPDATE` within a transaction, so concurrent requests against the same tenant serialize correctly without a separate advisory lock.

## `audit_log`

The single audit trail for every tenant-scoped action in the system — scheduled-job activity and live-session activity both write here, distinguished by whether `staff_identity` is populated.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `id` | `BIGSERIAL` (PK) | |
| `occurred_at` | `TIMESTAMPTZ` | Defaults to `now()`. Indexed (`idx_audit_log_occurred_at`) for the retention purge and any time-range queries. |
| `hub_id` | `TEXT` (nullable) | Indexed (`idx_audit_log_hub_id`). Nullable because not every conceivable event is tenant-scoped, though every event actually recorded today does populate it. |
| `staff_identity` | `TEXT` (nullable) | **`NULL` for scheduled-job activity, populated for live-session activity.** This is the field that distinguishes "the batch job pulled this tenant's data" from "this specific person queried this tenant's data live" — the only place either kind of attribution exists, since HubSpot itself only ever sees the one shared app credential. |
| `event_type` | `TEXT` | Free-form string, not an enum. Every value actually written today: `hubspot_install_completed`, `token_refreshed`, `token_invalidated`, `staging_cycle_completed`, `staging_cycle_failed`, `sybill_transcript_staged`, `live_tenant_selected`, `live_query`, `live_tenant_access_denied`, `audit_log_purge_failed`. |
| `detail` | `JSONB` | Defaults to `'{}'`. Shape varies per `event_type` — e.g. `staging_cycle_completed` carries `{"tables": [...]}`, `staging_cycle_failed` carries `{"error": "..."}`, `sybill_transcript_staged` carries `{"event_id": "..."}`. No fixed schema; treat as event-specific metadata, not a queryable structured column. |

Retention: SC-6 requires a 60-day minimum (`AUDIT_RETENTION_DAYS`). `auth/security.py::purge_expired_audit_log()` implements the delete, and runs on its own daily schedule (`main.py`'s `audit_log_purge` job, `scheduler.add_job(..., "interval", hours=24)`) — rows older than the retention window are actually pruned now, not just theoretically eligible for it.

## `staff_tenant_restrictions`

The live session's access-control table — a **deny-list**, not an allow-list. Presence of a row means "blocked," not "granted."

| Column | Type | Notes |
| :-- | :-- | :-- |
| `staff_identity` | `TEXT` | The `email` claim from the staff member's Google Workspace token. Comparisons are case-insensitive on both sides: `_require_staff_identity` lowercases the token's own email, and `_permitted_tenants`'s query compares against `LOWER(staff_identity)` — so a restriction row hand-typed with different casing than the token's email still matches and still applies. Stored as-typed, not normalized at write time. Part of composite PK. |
| `hub_id` | `TEXT` | Part of composite PK. Not a foreign key to `tenants` — a restriction can be added or left in place independent of whether that tenant is currently installed. |

Access model: any staff member who signs in successfully (passes the domain allowlist) has access to every tenant in `tenants` where `install_status = 'installed'`, **except** any `hub_id` for which a row exists here for their `staff_identity`. See `session/live_session.py::_permitted_tenants` for the exact query, and `design.md`'s decision log (`implement-hubspot-mcp-server`) for why this replaced an earlier allow-list design.

## `live_session_selection`

Tracks which tenant a given live session has selected — required whenever a staff member has more than one permitted tenant.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `session_id` | `TEXT` (PK) | The issued JWT's `jti` claim (or the raw token if `jti` is absent) — stable for one connected session's lifetime, per `session/live_session.py::_require_staff_identity`. |
| `staff_identity` | `TEXT` | Recorded alongside the selection so a session's selection can never be read or reused by a different staff identity, even if session IDs were ever guessable. |
| `selected_hub_id` | `TEXT` (nullable) | The chosen tenant. Upserted via `ON CONFLICT (session_id) DO UPDATE` — a staff member can change their selection mid-session by calling `select_tenant` again. |
| `created_at` | `TIMESTAMPTZ` | Set once at first insert. Nothing currently expires or cleans up old sessions' rows — like `oauth_states`, rows accumulate indefinitely (small, low-sensitivity rows; a `hub_id` selection, not a credential). |

## `hubspot_object_index`

Resolves which tenant a HubSpot object ID belongs to — the mechanism that lets the Sybill webhook figure out `hub_id` from a transcript payload that carries none of its own.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `object_type` | `TEXT` | Only `company` and `deal` are indexed today (`sync/airtable_staging.py::_index_crm_objects`) — the two types Sybill's `crmInfo.accountId`/`opportunityId` need to resolve against. Part of composite PK. |
| `object_id` | `TEXT` | HubSpot's own object ID. **Not globally unique across portals by itself** — the same numeric ID can exist in two different clients' portals. Part of composite PK. |
| `hub_id` | `TEXT` | The tenant that `(object_type, object_id)` belongs to. Part of composite PK. |

Populated as `company`/`deal` objects are staged by the scheduled sync job (`Source ID` from the staged Airtable row). Looked up via Sybill's `crmInfo.accountId`/`opportunityId` fields (`webhooks/sybill.py::resolve_hub_id`); a `(object_type, object_id)` pair is only trusted for tenant resolution if it maps to **exactly one** distinct `hub_id` — zero matches (not staged yet) or more than one (a same object ID colliding across two portals) are both rejected outright rather than guessed at, since a wrong guess here would be a cross-tenant leak. Indexed on `(object_type, object_id)` (`idx_hubspot_object_index_lookup`) for that lookup direction specifically.

## `analysis_content`

Blu Mountain's own-authored analysis content (`gateway/frameworks/`, see `openspec/changes/analysis-model-templates/`) — this project stores and serves this content verbatim, it never authors or edits it. Append-only by convention: `store.py::ingest()` always inserts a new row, never updates one in place, so a `tenant_onboarding_profile_fields.framework_guidance` value produced against an earlier version can never silently change out from under it.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `id` | `SERIAL` (PK) | |
| `content_type` | `TEXT` | One of six values, more than `schema.sql`'s own inline comment names (`vertical_framework`, `skill`, `prompt`) — confirmed from `frameworks/store.py`'s actual validated set: those three plus `challenge_library`, `operating_principles`, `template_library` (added task 7.1, the six per-vertical Challenge Library documents plus the two content-agnostic Blu Operating Principles / Template Library pieces). Enforced by `store.py::_validate_content_type` against a fixed set, not a DB-level `CHECK`. |
| `name` | `TEXT` | E.g. `saas`, `plg`, `marketplace`, `ecommerce`, `services-project`, `transactional` for `vertical_framework`; `account-diagnostic-skill` for `skill`; `weekly-diagnostic-prompt` for `prompt` — the skill/prompt types have exactly one real name each today, but nothing in the schema or code assumes that stays true. |
| `version` | `INTEGER` | 1 for a never-before-seen `(content_type, name)`, otherwise one more than the current max — computed in `ingest()`, not a DB sequence, so concurrent ingests of the same name could in principle race (accepted: this content is ingested occasionally and by hand, not under concurrent load). |
| `content` | `TEXT` | The verbatim document body. |
| `source_path` | `TEXT` (nullable) | Where the content was ingested from, if applicable. |
| `ingested_at` | `TIMESTAMPTZ` | Set once at insert. |

Unique on `(content_type, name, version)`; indexed on `(content_type, name, version DESC)` (`idx_analysis_content_lookup`) for `get_latest()`'s and `list_latest()`'s own query shape. Read by `frameworks/onboarding.py` (via `profiling.py`) when a profile auto-confirms a field against framework guidance, and by `frameworks/vertical.py`'s `KNOWN_VERTICALS` (derived from `ingest.py::FILE_MAP`, not this table directly) to validate a staff-set `tenants.vertical`.

## `tenant_onboarding_profiles`

A lightweight, named, per-tenant snapshot of which HubSpot fields are confirmed relevant for that tenant's analysis (task 3, `specs/tenant-template-instantiation/spec.md`) — the runtime parameter meant to accompany a shared vertical framework at invocation time, **never** a copy of the framework/skill/prompt itself, which stay shared and unmodified in `analysis_content` above.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `id` | `SERIAL` (PK) | Referenced by `tenant_onboarding_profile_fields.profile_id`. |
| `hub_id` | `TEXT` (`REFERENCES tenants(hub_id) ON DELETE CASCADE`) | Isolation is structural here, not just conventional: every read/write in `frameworks/onboarding.py` takes `hub_id` and enforces it directly in the query (a JOIN/WHERE clause) — a profile belonging to one tenant cannot be fetched or mutated through another tenant's `hub_id`, by construction, not just by caller discipline. |
| `name` | `TEXT` | A snapshot of the tenant's effective display name (`COALESCE(portal_name, hub_domain, hub_id)`) **at production time**, not a live join — matches `analysis_content`'s versioned-snapshot philosophy, so it doesn't silently change if the tenant is later renamed. |
| `vertical` | `TEXT` (nullable) | The vertical this specific profile was produced against — a point-in-time snapshot, distinct from the current, live-updatable `tenants.vertical`. `NULL` only if the profile was deliberately produced unqualified (`allow_unqualified=True`). |
| `created_at` | `TIMESTAMPTZ` | Set once at insert; `get_latest_profile_for_tenant()` orders on this to find a tenant's most recent profile. Nothing purges old profiles. |

Indexed on `hub_id` (`idx_tenant_onboarding_profiles_hub_id`). Produced by `frameworks/onboarding.py::produce_onboarding_profile()`, which reuses the existing, already-allowlisted `pull_crm_objects()` (no new HubSpot access path) via `frameworks/profiling.py`. Read by the vertical pull agent (task 8, `specs/vertical-pull-agent/spec.md`) via `get_latest_profile_for_tenant()`, to inject a client's confirmed-relevant fields into its per-tenant prompt.

## `tenant_onboarding_profile_fields`

One row per populated field a profile considered — only ever populated fields, since an unpopulated field has nothing to analyze regardless of framework guidance and is never a candidate.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `profile_id` | `INTEGER` (`REFERENCES tenant_onboarding_profiles(id) ON DELETE CASCADE`) | Part of composite PK. |
| `object_type` | `TEXT` | HubSpot object type the field belongs to (e.g. `contacts`, `deals`). Part of composite PK. |
| `property_name` | `TEXT` | Part of composite PK. |
| `status` | `TEXT` | `confirmed_relevant` (auto-confirmed at production time if the tenant's vertical framework already had explicit guidance — `trust_by_default` or `unreliable_by_default`, either counts as the framework actively discussing the field), `confirmed_irrelevant`, or `needs_review` (no framework guidance existed at production time — a human must decide via `review_field()`). A profile is "final" (`OnboardingProfile.is_final`) only once no field is left at `needs_review`. |
| `framework_guidance` | `TEXT` (nullable) | The framework's own guidance text for this field, carried over at auto-confirm time; `NULL` for a `needs_review` field. |
| `reviewed_by` | `TEXT` (nullable) | Set by `review_field()` when a human moves a field off `needs_review`. |
| `reviewed_at` | `TIMESTAMPTZ` (nullable) | Set alongside `reviewed_by`. |

`review_field()` scopes its `UPDATE` through a JOIN back to `tenant_onboarding_profiles.hub_id`, the same structural isolation as the profile table itself — a review action can never target a profile belonging to a different tenant.

## `vertical_agent_templates`

Added `openspec/changes/separate-vertical-client-agents` (2026-09-01) — a deliberate, knowing supersession of `analysis-model-templates/design.md`'s original Non-Negotiable #6 ("one agent config per vertical, shared across every client, no per-client persistence"); see that Non-Negotiable's own note for the full reasoning. One independently-editable, versioned agent template per vertical — this project's own tool/model configuration layered around a vertical framework's raw text (`analysis_content` above), never a copy of that framework itself, which stays shared, unmodified, and Blu-Mountain-authored.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `id` | `SERIAL` (PK) | Referenced by `client_agent_instances.vertical_template_id`. |
| `vertical` | `TEXT` | One of the six known verticals (`frameworks.vertical.KNOWN_VERTICALS`); validated at insert, not DB-enforced. |
| `version` | `INTEGER` | Append-only, same pattern as `analysis_content.version` — `ingest_template()` always inserts a new version, never updates one in place, so a `client_agent_instances` row built from an earlier version keeps reading that exact version even after the vertical's template is updated. |
| `system_prompt_additions` | `TEXT` | This vertical's own agent-configuration text (tool-use guidance, prioritization, style), layered after the raw framework text in the agent's system prompt (`frameworks/pull_agent.py::_system_prompt`). Empty string is valid and common — the six verticals were bootstrapped with empty additions specifically so day-one behavior didn't regress from the prior single-tier agent. |
| `tool_config` | `JSONB` | Defaults to `'{}'::jsonb`. Currently reads one optional key, `max_tool_calls` (overrides `pull_agent.MAX_TOOL_CALLS` for that vertical's runs) — not a fixed schema, room for more per-vertical tool/model parameters later. |
| `created_at` | `TIMESTAMPTZ` | Set once at insert. |

Unique on `(vertical, version)`; indexed on `(vertical, version DESC)` (`idx_vertical_agent_templates_lookup`) for `get_latest_template()`'s query shape. Staff-editable directly (`frameworks/vertical_templates.py::ingest_template`) — no separate review/ingestion pipeline, since this is this project's own configuration, not Blu Mountain's authored content.

## `client_agent_instances`

Added alongside `vertical_agent_templates` above, same change. The genuinely new per-client artifact this change introduces: one persisted, versioned agent instance per client, built from that client's vertical's current template plus that client's own injected documentation. Superseded the prior design's "context assembled fresh on every run, nothing persisted" model — this table is a durable, independently-editable per-client record now.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `id` | `SERIAL` (PK) | |
| `hub_id` | `TEXT` (`REFERENCES tenants(hub_id) ON DELETE CASCADE`) | Isolation is structural, matching `tenant_onboarding_profiles`: every read/write in `frameworks/client_agent.py` enforces `hub_id` directly in the query, never a Python-level check a caller could skip. |
| `vertical_template_id` | `INTEGER` (`REFERENCES vertical_agent_templates(id)`) | A real FK to the exact template version this instance was built from — not a copied `(vertical, version)` pair — so an instance is always traceable to precisely one template row, even after that vertical's template is later updated. |
| `version` | `INTEGER` | Append-only per `hub_id`, same versioned-snapshot philosophy as everywhere else in this project — a new instance is always a new row, never a mutation, so an in-flight run keeps using the version it started with. |
| `injected_documentation` | `TEXT` | A rendered snapshot of this client's onboarding-profile confirmed-relevant fields (same content shape as the prior ephemeral `pull_agent._client_context_block`, now persisted instead of recomputed on every run) — taken at production time, not a live join. |
| `created_at` | `TIMESTAMPTZ` | Set once at insert. |

Indexed on `(hub_id, created_at DESC)` (`idx_client_agent_instances_hub_id`) for `get_latest_client_agent_instance()`'s query shape. Produced by `frameworks/client_agent.py::produce_client_agent_instance()`, which refuses to run for a tenant with no known vertical (matching `produce_onboarding_profile`'s existing refusal posture) and refuses if the resolved vertical has no `vertical_agent_templates` row yet. `frameworks/pull_agent.py::run_client_agent(hub_id)` (replacing the old `run_pull_agent(hub_id, vertical)`) resolves — and produces on first use — the instance for every run.

## Locking (not a table)

Per-tenant refresh serialization (SC-4) uses `pg_advisory_xact_lock(hashtext(hub_id))` directly — a Postgres primitive keyed by the hash of the tenant's `hub_id` string, scoped to the current transaction (auto-released when it ends). There is no dedicated lock table; this is why `tokens` has no lock-related column. Two different tenants hash to (almost certainly) different lock keys, so they never block each other; two refreshes for the *same* tenant serialize correctly even across multiple service instances, since the lock lives in Postgres itself, not in any one instance's memory.

## Cross-cutting notes

- **Every tenant-scoped table keys on `hub_id` as plain `TEXT`**, not a surrogate integer ID — this is deliberate: `hub_id` is externally meaningful (it's HubSpot's own identifier) and appears in every log line, audit entry, and API response as-is, so there's no separate internal-ID-to-`hub_id` mapping to keep in sync anywhere.
- **Encryption at rest is scoped to exactly two columns**: `tokens.encrypted_access_token`/`encrypted_refresh_token` — the one vaulted credential, AES-256/HKDF, distinct per-tenant derived keys. Nothing else in this schema is encrypted at the column level — `staff_tenant_restrictions`, `audit_log`, etc. are plain text, which is fine since none of them hold a credential. (Formerly four columns, `mcp_tokens` included — dropped as part of the REST pivot, see that table's own note above.)
- **Nothing in this schema is ever hard-deleted except via the two explicit purges** described above (`oauth_states` on successful callback, `audit_log` via the daily scheduled retention purge) and the `ON DELETE CASCADE` chains from `tenants` — to `tokens` directly, to `tenant_onboarding_profiles` (which itself cascades to `tenant_onboarding_profile_fields`), and to `client_agent_instances`. Everything else (uninstalled tenants, old session selections, restriction rows, `analysis_content`, `vertical_agent_templates` — vertical-scoped, not tenant-scoped, so no cascade applies) is left in place indefinitely by design or by current omission — see each table's notes above for which is which.
- **This schema is applied against two separate real databases**: `mcp` (via `docker compose up`'s dev stack) and `mcp_test` (created automatically by `gateway/tests/conftest.py` on first test run). They share nothing — the test suite truncates every table it touches after each test, and running it against `mcp` directly destroyed a real, verified tenant install twice in one session before this separation was added.
