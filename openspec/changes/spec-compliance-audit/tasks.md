## 1. Section 2 — Authentication Architecture

- [x] 1.1 REQUIREMENT (2.1): app credentials shared across tenants, never conflated with tenant tokens — `config.settings` holds app credentials only; the `tokens` table holds tenant tokens only (implement-hubspot-mcp-server tasks 1.7)
- [x] 1.2 OAuth v3 flow: authorization redirect, user consent, code exchange at `/oauth/v3/token` with credentials in the body, token receipt — `gateway/auth/hubspot_oauth.py` (tasks 1.3-1.5)
- [x] 1.3 Handle RFC 6749 standardized error fields on token exchange failure — `hubspot_oauth.py::_parse_token_error` (task 1.6)
- [x] 1.4 Decide `/oauth/v3/introspect` usage and document the decision — decided not used; HubSpot has no v3 introspect endpoint, `/oauth/v1/access-tokens/{token}` resolves `hub_id` instead (task 1.8, design.md Open Questions)

## 2. Section 3 — Multi-Tenant Token Management

- [x] 2.1 `hub_id` as primary tenant key — `schema.sql` tenants/tokens tables (task 2.1)
- [x] 2.2 Portal-level vs. user-level indexing confirmed — portal-level (`context/Hubspot/IMPLEMENTATION_PLAN.md` #4/5); the live session's separate staff-to-tenant mapping (`staff_tenant_restrictions`) is a distinct mechanism, not a HubSpot token index
- [x] 2.3 AES-256 encryption at rest, never plain text — `gateway/auth/crypto.py`, AES-256-GCM with HKDF per-tenant key derivation (tasks 2.2/2.3), cross-tenant decryption proven impossible by test (task 2.10)
- [ ] 2.4 Managed secrets store (AWS Secrets Manager / HashiCorp Vault / GCP Secret Manager) for credentials and keys — **BLOCKED**: currently a single app-level key in `.env` only; deliberately resolved this way for MVP and explicitly reopened for the real hosting environment (`IMPLEMENTATION_PLAN.md` #4/5), matches `context/BLOCKERS.md` blocker #2. Cannot be built until a hosting/secrets-platform decision is made.
- [x] 2.5 Access-token cache: pluggable interface, TTL equal to expiry, refresh token never cached there — `gateway/auth/token_vault.py::AccessTokenCache`/`InMemoryAccessTokenCache` (task 2.5)
- [x] 2.6 Access-token cache: Postgres-backed implementation as the multi-instance baseline — **Resolved 2026-08-17**: `gateway/auth/token_vault.py::PostgresAccessTokenCache`, now `TokenVault`'s default. Reads the same encrypted row every instance already persists to `table_name` (no second table, no separate write path) — `set()`/`invalidate()` are deliberate no-ops. Required changing `AccessTokenCache`'s interface from sync to async (a real Postgres-backed implementation can't be sync), updating both call sites in `get_access_token()`/`invalidate_in_transaction()`, and fixing a real bug caught by the test suite during this fix: the cache's first version checked hard expiry only, not the 5-minute refresh buffer, so it served near-expiry tokens straight from the DB row and silently defeated proactive refresh — fixed to check `expires_at - _REFRESH_BUFFER`, same as `get_access_token()`'s own check. Five new tests including one proving the actual cross-instance property (`test_postgres_cache_visible_to_a_fresh_instance_that_never_wrote_it`). Full suite (179 tests) passes.
- [x] 2.7 Serialize concurrent refresh via Postgres advisory locks (multi-instance) — `pg_advisory_xact_lock(hashtext(hub_id))` in `token_vault.py` (task 2.7), load-tested (task 8.2)
- [x] 2.8 Proactive refresh on a five-minute buffer ahead of expiry — `token_vault.py::TokenVault.get_access_token` (task 2.6, spec Section 3.2)

## 3. Section 4 — MCP Server Connection

- [x] 3.1 Single MCP server, per-user OAuth with PKCE to HubSpot's remote MCP endpoint — `gateway/sync/hubspot_client.py::HubSpotDataPullClient` (task 3.1)
- [x] 3.2 MCP Auth App (4.1): separate shared Client ID/Secret, per-tenant tokens, mirrors the Public App's install/callback shape — `gateway/auth/mcp_auth.py`, `mcp_tokens` table, `auth.mcp_vault` (task 3.7)
- [x] 3.3 PKCE (4.2): 43-128 char verifier, S256 challenge, included in both the authorization request and the token exchange — `hubspot_oauth.py`/`mcp_auth.py` (task 1.3, mirrored for the MCP Auth App)
- [x] 3.4 No token passthrough (4.2) — the live session's FastMCP OAuth Proxy issues its own audience-scoped JWT; Google's own token never reaches the connecting client (task 6.3). The per-tenant HubSpot MCP connection itself uses the vaulted token directly server-side, never forwards it onward either.
- [x] 3.5 Client configuration (4.3): Authorization Code grant, MCP Auth App Client ID/Secret, access token as the JWT source — `hubspot_client.py::_client` (`StreamableHttpTransport` with `auth=access_token`)
- [x] 3.6 Data access surface (4.4): core objects (contacts, companies, deals, tickets, line items, products, calls, emails, meetings, notes, tasks) — confirmed live via `query_crm_data` (tasks 3.2, 3.8)
- [x] 3.7 Data access surface (4.4): reference objects (users, teams, owners, campaigns/metrics, landing pages, blog posts, segments) — confirmed live; "teams"/"segments"/"landing pages"/"blog posts" required a follow-up fix after an observability gap hid them (task 3.11)
- [x] 3.8 Read-only enforcement across the full object set — `hubspot_client.py::_is_read_safe`, an allowlist (not just a write-verb blocklist) since the MCP Auth App has no per-object OAuth scope grant of its own to rely on; role-permission scoping happens at HubSpot's end per the connecting user (task 3.4)

## 4. Section 5 — Tenant Isolation

- [x] 4.1 Credential vault isolation — per-tenant HKDF-derived AES-256-GCM key, proven cross-tenant-undecryptable by test (tasks 2.2/2.10)
- [x] 4.2 Tool definition isolation — implemented differently from the spec's literal per-tool framing, but the same underlying goal is met: the live session exposes a fixed 3-tool surface (`list_my_tenants`/`select_tenant`/`query_hubspot_data`) to every staff member regardless of tenant, while the actual per-tenant HubSpot tool/object availability is discovered dynamically per connection (`list_read_only_tools()`), so a tenant without Enterprise-tier `CAMPAIGN` access, for example, never has it exposed to begin with — no static per-tenant tool list was built because none was needed
- [x] 4.3 Context window isolation — `gateway/tests/test_tenant_isolation.py::test_live_session_two_staff_sessions_do_not_leak_selection`, `test_query_hubspot_data_never_constructs_a_client_for_a_restricted_tenant` (tasks 8.4, 6.8)
- [x] 4.4 Isolation pattern selection (5.1) — shared compute with per-tenant vault, the spec's own recommended default; matches the compliance-regime answer (no formal framework named, so no dedicated-container requirement triggered) — `IMPLEMENTATION_PLAN.md` #2

## 5. Section 6 — Security Controls (SC-1 through SC-10)

- [x] 5.1 SC-1 AES-256 encryption at rest — `crypto.py` (task 2.3)
- [x] 5.2 SC-2 tokens/secrets/client secrets never written to logs — `gateway/tests/test_credential_hygiene.py`, a static AST scan failing CI on any future credential-shaped log argument (task 7.4)
- [x] 5.3 SC-2 follow-up: confirm the real client's `SYBILL_WEBHOOK` secret was actually rotated — **Confirmed 2026-08-17**: rotated after the test-output leak flagged in `implement-hubspot-mcp-server` tasks.md 7.4.
- [x] 5.4 SC-3 OAuth `state` parameter validated on callback (CSRF) — `hubspot_oauth.py` (task 1.4)
- [x] 5.5 SC-4 per-tenant refresh serialized (Postgres advisory locks) — (task 2.7)
- [x] 5.6 SC-5 webhook signature validation (HMAC SHA-256), requests older than 5 minutes rejected — HubSpot uninstall webhook (task 2.8) and Sybill webhook (task 5.3) both confirmed
- [x] 5.7 SC-6 per-tenant audit logs, 60-day minimum retention — `audit_log` table, `security.py::record_audit`/`purge_expired_audit_log` (task 7.2)
- [x] 5.8 SC-7 per-tenant rate limiting (token-bucket) — `security.py::check_rate_limit` (task 7.1)
- [x] 5.9 SC-8 credentials never in model prompts, tool descriptions, or agent logs — same AST scan as SC-2 (task 7.4)
- [x] 5.10 SC-9 Sybill webhook payload signature validation, same basis as SC-5 — `webhooks/sybill.py::verify_svix_signature` (task 5.3); the receiver's tenant-resolution logic downstream of signature validation had two real bugs found and fixed 2026-08-17 — see Section 6 (FR-12) below, since that's a functional-correctness finding, not a signature-validation gap
- [x] 5.11 SC-10 every Airtable record tagged by client; staging writes preserve isolation end to end — `airtable_staging.py`, proven by test (tasks 4.4, 4.5)

## 6. Section 7 — Functional Requirements (FR-1 through FR-13)

- [x] 6.1 FR-1 install flow through OAuth v3 authorization and consent — `/install` (task 1.3)
- [x] 6.2 FR-2 persist issued token set keyed by portal on install — `_persist_new_tenant` (task 2.4)
- [x] 6.3 FR-3 uninstall/re-authorization support, invalidating stored tokens — (tasks 2.8, 2.9)
- [x] 6.4 FR-4 proactive refresh on a 5-minute buffer — (task 2.6)
- [x] 6.5 FR-5 cache access tokens with TTL=expiry; never cache refresh tokens — (task 2.5)
- [x] 6.6 FR-6 serialize concurrent refresh per tenant — (task 2.7)
- [x] 6.7 FR-7 connect to HubSpot's remote MCP with per-user OAuth and PKCE — (tasks 3.1, 3.7)
- [x] 6.8 FR-8 resolve correct tenant context per request — `HubSpotDataPullClient` constructed per `hub_id` (task 3.5); live session's `_resolve_selected_tenant`
- [x] 6.9 FR-9 expose only the tool set relevant to the requesting tenant — see Section 4.2 above
- [x] 6.10 FR-10 no tenant's data or errors cross into another tenant's session — (tasks 8.1-8.4)
- [x] 6.11 FR-11 stage normalized HubSpot data on the scheduled cycle, tagged by client — `run_staging_cycle` (tasks 4.3, 4.4), confirmed live against two real test portals (task 4.6)
- [x] 6.12 FR-12 (mechanism) Sybill webhook: validate signature, normalize, stage, tag by client — `webhooks/sybill.py` (tasks 5.2-5.5)
- [x] 6.13 FR-12 (correctness) — this was marked done in the other change's tracking (`implement-hubspot-mcp-server` tasks 5.1-5.6, all `[x]`) while carrying two real bugs that would have caused 100% of real Sybill events to fail: (1) `resolve_hub_id()` read a field (`data.crmInfo.accountId`/`opportunityId`) that never appears in Sybill's real payload, and (2) the underlying HubSpot pull never captured a usable object ID at all (`hubspot_object_index` was empty for every tenant, always). Both fixed 2026-08-17. **Confirmed 2026-08-17** (see task 10.5): a self-signed request using the real payload shape, the real trial signing secret, and the real indexed Deal (`hub_id=149094230`, `object_id=516897409255`) correctly verifies its signature, resolves to the right tenant, and a deliberately-unindexed ID correctly hits the reject path. Genuine production traffic (a real client live on both systems) still hasn't been observed, but the code path itself is now confirmed correct end to end, not just schema-shape-correct.
- [x] 6.14 FR-13 preserve tenant isolation across all staging writes — (task 4.5)

## 7. Section 8 — Non-Functional Requirements

- [x] 7.1 Security: all Section 6 controls met before production, least-privilege scopes by default — SC-1 through SC-10 done (Section 5 above), modulo task 5.3's rotation-confirmation follow-up
- [x] 7.2 Isolation: no cross-tenant data exposure under any code path, verified by test — (tasks 8.1-8.6)
- [x] 7.3 Reliability: token refresh and tenant resolution resilient to concurrent load **across instances** — resolved via task 2.6's `PostgresAccessTokenCache` fix; advisory-lock concurrency was already tested (task 8.2), and the cache is now genuinely shared across instances too, not just the lock.
- [x] 7.4 Observability: per-tenant audit logging **and metrics**; token-refresh and error rates monitored — audit logging is done (Section 5.7); a distinct metrics/rate-monitoring pipeline is **deliberately deferred, 2026-08-17** (see task 10.3) rather than silently missing — nothing depends on it today, since the deployment is a single locally-run instance diagnosed via logs/audit-log queries all session.
- [x] 7.5 Performance: tool definitions scoped per tenant to keep context windows lean — see Section 4.2 above
- [x] 7.6 Maintainability: one app and one server serve all tenants; adding a customer requires no new deployment — inherent to the `hub_id`-keyed, single-service architecture

## 8. Section 9 — Reference Stack

- [x] 8.1 Server runtime: FastAPI + FastMCP (mounted via ASGI) + uvicorn, HTTPS remote transport — `gateway/main.py`
- [x] 8.2 Token cache: Postgres-backed baseline + in-process fallback for local dev — resolved via task 2.6; both now exist, `PostgresAccessTokenCache` as the default and `InMemoryAccessTokenCache` kept available for explicit local-dev opt-in
- [x] 8.3 Concurrency control: Postgres advisory locks — done, and used unconditionally (even in local single-instance development) rather than only being reserved for a multi-instance path, which meets the spec's bar with room to spare
- [ ] 8.4 Secrets and vault: managed secrets store with per-tenant AES-256 — **BLOCKED**, duplicate of task 2.4 above; AES-256 itself is done, the managed store is not
- [x] 8.5 Persistence: encrypted Postgres token store keyed by portal identifier, also backing locks — done for the token store and locks; the "also backs cache" half of this line is the same Section 2.6/8.2 gap
- [x] 8.6 HubSpot: Public App (OAuth v3, read-only scopes) + remote MCP endpoint with PKCE — done (Sections 1-3 above)
- [x] 8.7 Observability: per-tenant audit logs and metrics pipeline — duplicate of task 7.4 above; audit logs done, metrics pipeline deliberately deferred (task 10.3)
- [x] 8.8 Sybill ingestion: webhook receiver with payload-signature validation, normalizes and stages per client — done as a mechanism (Section 6.12); see task 6.13's correctness caveat
- [x] 8.9 Staging integration: scheduled service writing normalized, per-client-tagged HubSpot and Sybill data into Airtable; Airtable is the only read-write integration — confirmed no HubSpot write code path exists anywhere in the codebase (`_is_read_safe`/`_is_safe_select` allowlists are the enforcement, not just a scope claim)

## 9. Section 10 — Assumptions and Open Items (mapped against `IMPLEMENTATION_PLAN.md`'s actual answers, not `implement-hubspot-mcp-server` tasks.md 9.2's non-matching six-item list)

- [x] 9.1 Item 1 — exact read-only HubSpot scopes: confirmed, full standard field set of Section 4.4's objects (`IMPLEMENTATION_PLAN.md` #1; tasks 1.1, 3.11)
- [x] 9.2 Item 2 — portal-level vs. user-level authorization: confirmed portal-level (`IMPLEMENTATION_PLAN.md` #4/5)
- [x] 9.3 Item 3 — compliance regime: confirmed as "none formally named; isolation stated as an absolute requirement instead" (`IMPLEMENTATION_PLAN.md` #2) — doesn't change the shared-vault architecture, and the isolation test suite (Section 4 above) already meets the raised bar this answer implies
- [x] 9.4 Item 4 — expected tenant count/peak concurrency: confirmed, ~50 active clients (`IMPLEMENTATION_PLAN.md` #3); no specific peak-concurrency figure was given beyond "multi-instance from launch," which the advisory-lock design already assumes unconditionally
- [ ] 9.5 Item 5 — secrets-management platform: **the one spec open item that is genuinely still open**, not just resolved-and-forgotten. Resolved only as a single app-level key for MVP, explicitly reopened for the real hosting environment (`IMPLEMENTATION_PLAN.md` #4/5) — matches `context/BLOCKERS.md` blocker #2, duplicate of task 2.4 above. `implement-hubspot-mcp-server` tasks.md 9.2 does not surface this nuance at all.
- [x] 9.6 Item 6 — Sybill delivery mechanism: confirmed webhook (design.md decision log; `IMPLEMENTATION_PLAN.md` #8)
- [x] 9.7 Item 7 — Airtable staging-table schema: confirmed, designed and provisioned live, 21 tables (design.md Open Questions; tasks 4.1, 4.6)

## 10. Follow-up work surfaced by this audit (not previously tracked anywhere)

- [x] 10.1 Build `PostgresAccessTokenCache` implementing the existing `AccessTokenCache` interface (`gateway/auth/token_vault.py`), and make it `TokenVault`'s default — done, see task 2.6
- [x] 10.2 Confirm (or perform) rotation of the real client's `SYBILL_WEBHOOK` secret — **Confirmed 2026-08-17**: already rotated after the leak flagged in `implement-hubspot-mcp-server` tasks.md 7.4
- [x] 10.3 Decide whether a dedicated metrics pipeline is worth building now (spec Section 9) or explicitly deferred until production monitoring is needed — **Decided 2026-08-17: deferred.** Nothing depends on it today (single local instance, diagnosed via logs/`audit_log` queries all session); revisit once production monitoring is actually needed. Recorded here so it's a deliberate deferral, not a silent gap.
- [x] 10.4 Update `implement-hubspot-mcp-server` tasks.md 9.2 to cite `IMPLEMENTATION_PLAN.md`'s actual seven-item answer table instead of its own six-item list — done; item left unchecked there since #5 (secrets platform) is still genuinely open
- [x] 10.5 Complete FR-12's real-traffic correctness confirmation (task 6.13 above) — done via a self-signed local test (real payload shape, real trial secret, real indexed Deal), run entirely in-process against the running container with no changes to `.env` or the container's environment; genuine production Sybill traffic is still a separate, later confirmation once a client is live on both systems
