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
| `hub_id` | `TEXT` (PK) | HubSpot's portal identifier. Primary tenant key referenced by `tokens`, `rate_limit_buckets`, `audit_log`, `staff_tenant_restrictions`, `hubspot_object_index`. |
| `portal_name` | `TEXT` | Reserved for a human-readable portal name. **Not currently populated by any code** — always `NULL` today. Nothing reads it either; safe to fill in later if a display name becomes useful, but it's dead weight right now. |
| `install_status` | `TEXT` | `'installed'` (default, set on every successful `/callback`) or `'uninstalled'` (set by `auth/token_vault.py` when HubSpot's uninstall webhook fires). This is the flag that determines which tenants the scheduled sync (`sync/airtable_staging.py`) and the live session's default-open access (`session/live_session.py::_permitted_tenants`) both treat as "active" — an uninstalled tenant's row is kept, not deleted, but excluded from both. |
| `installed_at` | `TIMESTAMPTZ` | Set once at first insert, never updated on re-install. |
| `updated_at` | `TIMESTAMPTZ` | Bumped on every `install_status` change (re-install or uninstall). |

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

## `mcp_tokens`

Same shape and purpose as `tokens` above, for a different credential: the MCP Auth App (spec Section 4.1), not the Public App. HubSpot's remote MCP endpoint (`mcp.hubspot.com`) is confirmed to be its own OAuth resource server (its own RFC 9728/8414 metadata, its own `oauth/v3/token` endpoint) and does not accept the Public App's CRM-scoped token — this table exists because that's a genuinely separate credential with its own independent refresh lifecycle, not because of any duplication. `hub_id` for this credential comes directly from the token-exchange response body, confirmed live; its introspection endpoint (`/oauth/v3/token/introspect`) returns only RFC 7662's minimal `{"active": true/false}`, no portal identifier, so `mcp_auth.py` doesn't call it at all.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `hub_id` | `TEXT` (PK, `REFERENCES tenants(hub_id) ON DELETE CASCADE`) | Same tenant identifier as `tokens`, but this row is only created by the MCP Auth App's own install (`/callback/mcp-auth`), a separate step from the Public App's install that creates the `tenants` row itself. Must happen second — `auth/mcp_auth.py`'s callback checks for a matching `tenants` row first and returns `409` with an explicit message if it's missing, rather than surfacing a raw FK-violation error. |
| `encrypted_access_token` | `TEXT` | Same AES-256/HKDF scheme as `tokens`. |
| `encrypted_refresh_token` | `TEXT` | Same scheme; `grant_types_supported` on `mcp.hubspot.com`'s own metadata confirms `refresh_token` is supported, same as the Public App. |
| `expires_at` | `TIMESTAMPTZ` | Same 5-minute proactive-refresh buffer, via a second `TokenVault` instance (`auth.mcp_vault`) constructed with `table_name="mcp_tokens"` and `mcp_auth.refresh_token_pair` — `TokenVault` was made parameter­izable specifically so this table didn't need its own duplicated vault class. |
| `last_refreshed_at` | `TIMESTAMPTZ` | Same as `tokens`. |

Read by `sync/hubspot_client.py::HubSpotDataPullClient` exclusively — this is the token actually used to connect to `mcp.hubspot.com`; `tokens` (the Public App's) is never used for that connection.

## `oauth_states`

Short-lived, in-flight PKCE state for Flow B, between `/install` and `/callback`.

| Column | Type | Notes |
| :-- | :-- | :-- |
| `state` | `TEXT` (PK) | Random `secrets.token_urlsafe(32)` value, round-tripped through HubSpot's authorize URL and back. |
| `code_verifier` | `TEXT` | The PKCE verifier generated alongside the state; retrieved and deleted together on a valid `/callback`. |
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

## Locking (not a table)

Per-tenant refresh serialization (SC-4) uses `pg_advisory_xact_lock(hashtext(hub_id))` directly — a Postgres primitive keyed by the hash of the tenant's `hub_id` string, scoped to the current transaction (auto-released when it ends). There is no dedicated lock table; this is why `tokens` has no lock-related column. Two different tenants hash to (almost certainly) different lock keys, so they never block each other; two refreshes for the *same* tenant serialize correctly even across multiple service instances, since the lock lives in Postgres itself, not in any one instance's memory.

## Cross-cutting notes

- **Every tenant-scoped table keys on `hub_id` as plain `TEXT`**, not a surrogate integer ID — this is deliberate: `hub_id` is externally meaningful (it's HubSpot's own identifier) and appears in every log line, audit entry, and API response as-is, so there's no separate internal-ID-to-`hub_id` mapping to keep in sync anywhere.
- **Encryption at rest is scoped to exactly four columns**: `tokens.encrypted_access_token`/`encrypted_refresh_token` and `mcp_tokens.encrypted_access_token`/`encrypted_refresh_token` — the two vaulted credentials, encrypted identically (same AES-256/HKDF scheme, distinct per-tenant derived keys). Nothing else in this schema is encrypted at the column level — `staff_tenant_restrictions`, `audit_log`, etc. are plain text, which is fine since none of them hold a credential.
- **Nothing in this schema is ever hard-deleted except via the two explicit purges** described above (`oauth_states` on successful callback, `audit_log` via the daily scheduled retention purge) and the `ON DELETE CASCADE` from `tenants` to `tokens` and `mcp_tokens` alike. Everything else (uninstalled tenants, old session selections, restriction rows) is left in place indefinitely by design or by current omission — see each table's notes above for which is which.
- **This schema is applied against two separate real databases**: `mcp` (via `docker compose up`'s dev stack) and `mcp_test` (created automatically by `gateway/tests/conftest.py` on first test run). They share nothing — the test suite truncates every table it touches after each test, and running it against `mcp` directly destroyed a real, verified tenant install twice in one session before this separation was added.
