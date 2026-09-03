## Context

Every HubSpot pull in this project goes through `gateway/sync/hubspot_client.py::HubSpotDataPullClient`, which today talks exclusively to `mcp.hubspot.com` using a second, separate vaulted credential (the MCP Auth App, `mcp_tokens` table, `gateway/auth/mcp_auth.py`). This was the original spec's own design choice (`HubSpot_MCP_Server_Spec_v1.2.md` Section 1.3: "HubSpot's remote MCP server is designed for exactly this multi-account pattern"), not something this build introduced.

This session's investigation, prompted by a direct question about whether the Public App is still needed, found:
- The Public App's own vaulted token (`tokens` table) is never read by any live pull path — confirmed by tracing every caller.
- `mcp.hubspot.com` is a fully independent OAuth resource server with its own consent screen and its own per-object permission grant (confirmed against `ONBOARDING_RUNBOOK.md`'s own documented install flow) — it was never "gated by" the Public App's scopes in the first place.
- HubSpot's plain REST API has real, better equivalents for what this project uses MCP for today: `GET /crm/v3/properties/{objectType}` returns an authoritative `hubspotDefined` boolean (something MCP's `search_properties` doesn't expose, which is why `is_custom_property_name()`'s heuristic exists at all), and `GET /marketing/v3/emails/statistics/list` is a confirmed real REST equivalent for marketing email analytics.
- This project's own `HubSpotDataPullClient` already presents a clean method interface (`pull_crm_objects`, `discover_object_properties`, `pull_object`, `pull_campaign_data`) that everything downstream depends on — `frameworks/profiling.py`, `frameworks/pull_agent.py`, `session/live_session.py`'s four category tools, `sync/airtable_staging.py` — none of which touch MCP specifics directly.

## Goals / Non-Goals

**Goals:**
- Replace `mcp.hubspot.com` with HubSpot's plain REST API (`api.hubapi.com`) as the sole HubSpot data-access mechanism, using only the Public App's existing vaulted token.
- Preserve `HubSpotDataPullClient`'s public method signatures so downstream code changes minimally.
- Remove the MCP Auth App, its install flow, and its token vault entirely — not leave it half-retired.
- Every real capability this project currently reaches via MCP either gets a confirmed-live REST equivalent, or is explicitly flagged as a capability being knowingly dropped — never silently lost.
- A Postman collection for this service's own exposed HTTP endpoints, once the post-migration route set is final.

**Non-Goals:**
- No change to HubSpot's read-only posture — still absolutely no write scopes, no write code paths, ever.
- No change to the vertical/client agent separation's own persistence model, the live session's Google OAuth Proxy, Airtable staging's own logic, or Sybill ingestion — only what feeds them changes (REST-sourced data instead of MCP-sourced data), not their own behavior.
- Does not attempt to reach genuinely custom (non-standard) HubSpot objects in this change — that's still a separate, tracked gap (see Open Questions); this change is about replacing MCP with REST for what's already reachable, not expanding scope to also close the custom-object gap in the same pass.
- Does not change the Public App's own OAuth install flow (`auth/hubspot_oauth.py`) at all — it already works, already vaults a token, already refreshes it.

## Non-Negotiables

Carried forward from this project's standing rules, plus one new one specific to this change:

1. No write operations against HubSpot, ever. **Unchanged.**
2. No HubSpot Private App tokens. **Unchanged.**
3. Every multi-tenant code path still requires an isolation test before it's considered done. **Unchanged** — every isolation test currently proving "one tenant's pull never touches another's token/data" needs an equivalent proof against the new REST-based client, not just a carried-over assumption that it still holds.
4. **New**: no real capability currently reachable via MCP is silently dropped. Each of the five generic MCP tools this project currently uses (`search_owners`, `get_organization_details`, `get_content_analytics_report`, `get_marketing_email_analytics`, `get_campaign_attribution_reports`) needs its REST mapping confirmed live before that MCP path is removed — see Decisions below for which are already confirmed vs. still open.

## Decisions

**REST endpoint mapping — confirmed vs. needs live confirmation during implementation.** Not guessed at uniformly; here's the honest split:

*Confirmed real REST equivalents exist:*
- Core CRM object list (CONTACT, COMPANY, DEAL, TICKET, LINE_ITEM, PRODUCT, CALL, EMAIL, MEETING_EVENT, NOTE, TASK, USER) → `GET /crm/v3/objects/{objectType}`, paginated, with `properties=` for explicit column selection. This project's own pulls never use a WHERE-clause-equivalent filter today (`pull_crm_objects`'s SQL is always `SELECT hs_object_id, * FROM {TYPE}`, no filtering) — so the plain list endpoint is a direct match, not the more complex `/search` POST endpoint with filter groups.
- Custom/standard property discovery → `GET /crm/v3/properties/{objectType}`, returns `hubspotDefined` per property directly — this is a real improvement over MCP's `search_properties`, not just parity, and lets `is_custom_property_name()`'s heuristic be retired for any object type this endpoint covers.
- Marketing email analytics → `GET /marketing/v3/emails/statistics/list` (confirmed via HubSpot's own developer docs during this session's research).
- Owners → `GET /crm/v3/owners/`.

*Real, but a different API family than the core CRM objects* — this is the one piece of genuine new complexity the REST rebuild has to handle, worth naming explicitly rather than glossing over: `LANDING_PAGE`/`BLOG_POST` live under HubSpot's CMS API family, `CAMPAIGN` under the Marketing Campaigns API, `OBJECT_LIST` (segments) under the Lists API — none of these share `/crm/v3/objects/`'s shape the way the 16 "core" types mostly do. MCP's `query_crm_data` dialect hid this behind one uniform SQL-like interface; REST doesn't. Each needs its own thin adapter inside `HubSpotDataPullClient`, not a single generic loop.

*Needs confirming live during implementation, not assumed:* `get_organization_details`'s REST equivalent (likely under HubSpot's Settings/Account-Info APIs, exact path unconfirmed), `get_content_analytics_report`'s equivalent (HubSpot's Analytics API is less uniformly documented than the CRM v3 APIs), and `get_campaign_attribution_reports`'s equivalent (likely the Marketing Campaigns API's own per-campaign reporting endpoints). Tasks below scope each of these as its own "confirm the real endpoint, then implement" step — per Non-Negotiable #4, none of the three gets removed from the MCP path until its replacement is confirmed live.

**Auth: reuse the existing Public App vault, reuse `httpx`, drop the MCP `Client`/transport machinery entirely.** `HubSpotDataPullClient` currently builds a `fastmcp.Client` over `StreamableHttpTransport`. The rebuilt version instead does what `auth/hubspot_oauth.py` already does elsewhere in this project: an `httpx.AsyncClient` call with `Authorization: Bearer {access_token}`, where `access_token` comes from the existing `auth.vault` (the Public App's `TokenVault` instance, already proactively refreshing on the standard 5-minute buffer) instead of `auth.mcp_vault`. No new vault, no new refresh logic, no new dependency — `httpx` is already a direct dependency of this project.

*Alternative considered — keep both vaults, fall back to REST only where MCP fails.* Rejected: this would mean carrying two credentials, two install steps, and two data-access code paths indefinitely, which defeats the entire point of this change (removing the MCP Auth App, not just adding a second path alongside it).

**Dynamic tool discovery/allowlisting is removed, not ported.** `list_read_only_tools`, `_is_read_safe`, `_has_write_verb`, `IN_SCOPE_OBJECT_KEYWORDS` all exist because MCP's tool surface is discovered at runtime and isn't fully known ahead of time — the same reason `get_organization_details` was once silently excluded until someone read the exclusion-logging bucket. REST's endpoint set is fixed and fully documented by HubSpot; this project will call a small, explicit, hand-maintained set of endpoints it knows about, the same posture `CRM_OBJECT_TYPES` itself already uses for the object-type list. No runtime discovery step is needed or wanted.

*Alternative considered — keep a lighter version of the allowlist as defense-in-depth even without dynamic discovery.* Partially adopted: `_is_safe_select`'s SQL-injection-style defense-in-depth posture doesn't map to REST (there's no SQL to validate), but the same *spirit* — never trust scope/intent alone — carries forward as: every REST call this project makes is a GET (or, where genuinely needed, a narrowly-scoped read-only POST like `/crm/v3/objects/{type}/search` if that's ever needed later) to a hand-enumerated, reviewed endpoint list, never a caller-constructed URL.

**Rate limiting: rely on the existing per-tenant Postgres token-bucket (SC-7) as the primary control, add 429 handling as defense in depth.** HubSpot's REST API enforces its own per-portal rate limits and returns `429` with a `Retry-After` header when exceeded — this project's existing rate limiter (`auth/security.py::check_rate_limit`) already exists to keep this project's own outbound request rate sane per tenant; the rebuilt client additionally needs to handle a `429` gracefully (log, back off, don't crash the pull) rather than assuming the token-bucket alone prevents ever seeing one.

**Testing: fake `httpx` responses, matching `auth/hubspot_oauth.py`'s own existing test pattern, not a new mocking dependency.** `test_hubspot_oauth.py` already fakes `httpx.AsyncClient` calls for the Public App's own OAuth exchange — the rebuilt `hubspot_client.py`'s tests follow the same pattern for consistency, rather than introducing a new HTTP-mocking library (e.g. `respx`) this project doesn't already depend on.

## Migration Plan

This is the part that needs the most care — `mcp_tokens` holds real, live, AES-256-encrypted vaulted tokens for two real installed portals (`148997330`, `149094230`) right now.

1. Build and test the REST-based `HubSpotDataPullClient` fully, in parallel with the existing MCP-based one still in place and still working — nothing about the MCP path is removed yet at this stage.
2. Confirm live, against both real test portals, that every pull path (core CRM objects, custom-property discovery, and each of the confirmed/newly-confirmed generic-tool equivalents) returns real, correct data via REST — matching or exceeding what MCP currently returns.
3. Only once step 2 is confirmed: cut over `HubSpotDataPullClient` to REST internally, remove the MCP `Client`/transport code, remove `gateway/auth/mcp_auth.py` and its routes.
4. **Revoke, don't just abandon, the real vaulted MCP Auth App tokens** before dropping their table — HubSpot's OAuth v3 supports token revocation; call it for both real portals' vaulted MCP Auth App tokens as an explicit step, so those credentials are actually invalidated on HubSpot's side, not just forgotten about in an unused table.
5. Drop `mcp_tokens` via an explicit `DROP TABLE IF EXISTS mcp_tokens;` in `schema.sql` — this project already has a precedent for exactly this (`DROP TABLE IF EXISTS staff_tenant_permissions;`, from the earlier allow-list-to-deny-list migration), applied idempotently on every startup, not a manual one-off migration script.
6. Remove `HUBSPOT_MCP_*` variables from `.env.example` and `docker-compose.yml` only after step 5, matching the existing precedent of removing config once nothing reads it (see `FASTMCP`-adjacent variable cleanup done earlier this session).
7. Rollback path: since steps 1-2 never touch the existing MCP path, the rollback for any problem discovered before step 3 is simply "don't cut over yet." After step 3, rollback would mean reverting the code change and re-installing the MCP Auth App fresh for any portal — there's no way to "undo" step 4's revocation, so step 3 onward should only happen once step 2's live confirmation is genuinely solid, not provisional.

## Risks / Trade-offs

- **[Risk] Some of the five generic MCP tools may not have a clean 1:1 REST equivalent** (content analytics and campaign attribution are the least certain). → Mitigation: Non-Negotiable #4 — nothing gets removed from the MCP path until its replacement is confirmed live; if a real equivalent genuinely doesn't exist, that's surfaced explicitly as a capability trade-off for a human decision, not silently dropped.
- **[Risk] REST introduces multiple API families (CRM, CMS, Marketing, Lists) where MCP presented one uniform interface.** → Mitigation: named explicitly in Decisions above; each family gets its own small, well-tested adapter inside `HubSpotDataPullClient`, not forced into one generic loop that doesn't fit.
- **[Risk] This is a large, cross-cutting rebuild touching most of the pull-dependent test suite.** → Mitigation: `HubSpotDataPullClient`'s public interface is preserved specifically so downstream tests (`test_pull_agent.py`, `test_profiling.py`, `test_live_session.py`, `test_airtable_staging.py`) need minimal changes; only `test_hubspot_client.py` itself needs a substantial rewrite of its fakes.
- **[Risk] `mcp_tokens` removal is irreversible once tokens are revoked.** → Mitigation: the Migration Plan's staged approach — build and confirm REST fully before touching anything MCP-related, revoke deliberately as its own step, never a blind `DROP TABLE` as the first move.
- **[Trade-off] Losing the MCP Auth App also means losing whatever convenience its consent screen gave portal admins** (a single, MCP-specific per-object read/write choice at install). Accepted: the Public App's own scoped consent (`HUBSPOT_SCOPES`) already governs read access at that layer, and onboarding actually gets simpler — one install step instead of two.

## Open Questions

- Whether to pursue genuine custom-object access (objects beyond the ~30 standard types, e.g. a real marketplace client's own "Provider" object) is explicitly not decided by this change — REST has its own schema-discovery endpoints for this, but it's separate scope, tracked here as a known follow-on, not silently folded in.
- Whether `get_organization_details`, `get_content_analytics_report`, and `get_campaign_attribution_reports` all have clean REST equivalents is genuinely unresolved until the corresponding implementation tasks run — see Decisions above for the honest confidence split.
- Whether the real MCP Auth App registrations (in HubSpot's developer account) should also be deleted, not just have their tokens revoked, is a decision for whoever manages that developer account — outside what this codebase can do.
