# Current Blockers and Available Work

What's actually blocking further progress right now, why, and what can still
be worked on in the meantime. Kept separate from `context/Hubspot/IMPLEMENTATION_PLAN.md`
(the original planning document) since that document narrates history as it
happened; this one is meant to be replaced wholesale each time the blocker
picture changes, not appended to.

Last confirmed accurate: 2026-09-02, after `openspec/changes/separate-
vertical-client-agents` (vertical/client agent separation, custom HubSpot
field access, the live session's category-scoped query tools) was built,
tested, and confirmed live against both real test portals, then followed
by two codebase-wide refactor/simplification passes (real duplication
removed across `frameworks/`, `auth/`, `sync/`, `main.py`, `config.py`;
dead code and one unused dependency removed; one real config gap closed —
`FASTMCP_ACCESS_TOKEN_TTL_MINUTES` was documented but never wired into
`GoogleProvider`), each re-verified live afterward — 288/288 tests
passing, all confirmed against real Postgres/HubSpot/Anthropic via
`gateway/scripts/live_verification.py`, not just unit tests. See that
change's `tasks.md`. Previously confirmed accurate:
2026-08-25, after Sections 1-3 of the
`analysis-model-templates` change (vertical-framework storage, tenant field
profiling, tenant onboarding profiles) were built, tested (218/218 passing),
and confirmed live against both real test portals — see
`openspec/changes/analysis-model-templates/tasks.md`. Also reflects
2026-08-17's real, live, end-to-end confirmation of the live session's
Google OAuth Proxy (a real Google login through MCP Inspector, full
DCR/authorize/consent/token-exchange flow, re-confirmed again via a real
`/install`/`/install/mcp-auth` reinstall), the Airtable staging pipeline (a
real base created, schema provisioned via `ensure_schema()`, and a real
pull-and-stage cycle run against both test portals), and the live session's
three tools themselves (`list_my_tenants`, `select_tenant`,
`query_hubspot_data`) — exercised for real through MCP Inspector and covered
by automated real-`Client`↔`FastMCP`-transport tests, not just connected —
see `openspec/changes/implement-hubspot-mcp-server/design.md`'s decision log
for the full history.

## Blocked (needs an external action, not resolvable by writing more code)

### 1. Real Sybill traffic — needed to validate one open edge case

**What's blocked:** Confirming task 5.6's flagged open item: whether an
ambiguous or unmatched `data.crm` reference in a real Sybill payload behaves
as expected (rejected, not guessed at) under real traffic hitting our own
receiver, rather than constructed test fixtures or a payload example
obtained from elsewhere. The `crm.type` string mapping itself is no longer
part of this blocker — both `"opportunity"` and `"account"` are now
confirmed live (a real production payload for a company-linked meeting,
obtained 2026-08-19, used `type: "account"`).

**Why:** This needs an actual Sybill webhook delivery hitting the receiver,
which needs Sybill actually configured to send them for a real client
account.

**What's NOT blocked by this:** everything else about Sybill ingestion.
Whether webhook or polling was the real delivery mechanism (spec open item
#6) is resolved — webhook, decided 2026-08-15 on the credential actually
provisioned (a live-mode `SYBILL_WEBHOOK` signing secret; no polling
credential of any kind exists — a vendor doesn't hand out a webhook secret
for an integration that isn't using webhooks). Signature validation,
normalization, and staging are all built and tested (tasks.md Section 5,
items 5.1-5.6, all `[x]`) — **note:** tenant resolution had a critical
schema bug (`data.crmInfo.accountId`/`opportunityId`, which never appears in
Sybill's real payload) that would have caused every real event to be
rejected; found and fixed 2026-08-17 against a real payload obtained from
the user's own Sybill trial account, see design.md's decision log. This
blocker is now a real-traffic validation step for the corrected code, not
missing functionality or an unresolved design question.

**Who unblocks it:** whoever manages the Sybill integration on Blu Mountain's
side, once at least one client has both Sybill and this system live. No
request to send yet — nothing to ask for until a real client is live on
both.

### 2. Production hosting, subdomain, managed Postgres, secrets platform

**What's blocked:** Deploying anywhere other than a local machine.

**Why:** No subdomain/DNS/TLS, managed Postgres instance, or production
secrets platform has been provisioned yet (`context/Hubspot/IMPLEMENTATION_PLAN.md`
Section 4.5). Production OAuth redirect URIs for both HubSpot and Google
can't be registered until the subdomain exists.

**What's NOT blocked by this:** all local development, testing, and the real
credentialed HubSpot/Google/Airtable testing already done. This only matters
once onboarding a real (non-test) client portal becomes the goal.

**Who unblocks it:** whoever can create/delegate the hosting account.

**Request to send:** *"We need a subdomain (e.g. `mcp.blumountain.com`) with
DNS and TLS, a managed Postgres instance, and a decision on a
secrets-management platform before this can run anywhere but a local
machine. To set this up: confirm the hosting account (Hostinger was the
original recommendation) and delegate admin access to Gumpper Group — or let
us know if a different host is preferred."*

### 3. Analysis framework content-format and validation decisions — needs Blu Mountain's strategy side

**What's blocked:** Two open questions from `analysis-model-templates`
Section 5 that this project can't resolve unilaterally, plus one it hasn't
formally tracked yet:

- Whether the six delivered "Challenge Library" documents need reformatting
  into real Claude Skill-format bodies (matching `account-diagnostic-SKILL.md`'s
  own structure), or are fine as reference-only catalogs the operational
  skill loads as context.
- What validation/testing methodology would prove a vertical framework or
  the skill actually works — Blu Mountain's own `Blu_Operating_Principles.md`
  lists this as pending on their end too (expanding from 4 to 36+ tracked
  clients, outcome correlation), not something already decided.
- Where the three downstream analysis jobs (Funnel, Maintenance, KPIs &
  Reporting) should actually live — this repo, or a separate service that
  only consumes what this repo produces (staged Airtable data, stored
  frameworks, tenant onboarding profiles). Not yet added to `tasks.md`
  Section 5 as its own tracked item; flagged here in the meantime since it's
  the same kind of external decision as the other two.

**Why:** None of these are code questions — they're decisions about how Blu
Mountain wants its own methodology packaged and validated, and about where
Blu Mountain wants the eventual analysis jobs hosted.

**What's NOT blocked by this:** Sections 1-3 (framework storage, field
profiling, onboarding profiles) are built and confirmed live regardless of
how these three questions resolve — none of them changes what's already
built, only what gets built next.

**Who unblocks it:** whoever owns analysis methodology on Blu Mountain's
side.

**Request to send:** *"Before we build the three analysis jobs that consume
the frameworks and onboarding profiles, we need your input on three things:
(1) should the six Challenge Library documents be reformatted into
Skill-format bodies, or are they fine as reference catalogs as delivered?
(2) what's the validation methodology for confirming a framework or the
skill is actually working for a client — is this decided on your end yet?
(3) should the analysis jobs (Funnel, Maintenance, KPIs & Reporting) run
inside this service, or in a separate system that just reads what we
produce?"*

## Resolved since the last version of this file

- **The `"account"` crm.type mapping is now confirmed live**, not just
  inferred — a real production Sybill payload for a company-linked meeting
  (`crm: {id: "53106879777", name: "Accelerated Analytics", type:
  "account"}`) was obtained 2026-08-19, confirming `resolve_hub_id()`'s
  `account` → `company` mapping against a real event, matching
  `"opportunity"` → `deal`'s earlier confirmation. The hub_id itself wasn't
  resolvable from this specific payload (a real client portal, not one of
  this project's own test portals), so the remaining edge-case validation
  in this blocker is now purely about traffic reaching our own receiver,
  not about the type mapping.
- **Sybill tenant resolution's payload schema was wrong** — `resolve_hub_id()`
  read `data.crmInfo.accountId`/`opportunityId`, a field that never appears
  in Sybill's real payload; every real event would have been rejected.
  Found via a real "Test"-button payload from the user's own Sybill trial
  account, fixed to read the real `data.crm.id`/`data.crm.type` shape, and
  the three affected unit tests rewritten to match. See design.md's
  decision log for the full account.
- **`hubspot_object_index` had been empty for every tenant, always** —
  found while seeding real test data to actually exercise the fix above.
  `pull_crm_objects()`'s `SELECT * FROM {TYPE}` never returns a CRM
  object's own ID (confirmed live: HubSpot's default property set
  excludes it, and `id` isn't a valid property name — `hs_object_id` is,
  nested inside `properties`). Every CRM object staged since this was
  first built had a blank Source ID, so nothing was ever indexed — meaning
  Sybill's tenant resolution could never have succeeded, on either test
  portal, even after the fix directly above. Fixed by selecting
  `hs_object_id` explicitly and reading it from the right place; confirmed
  live by re-running the pull against both real test portals and seeing
  real rows land in `hubspot_object_index` for the first time. See
  design.md's decision log.
- **Google Cloud OAuth client for the live session** — previously blocked on
  a manual credential registration. Now resolved: `FASTMCP_GOOGLE_CLIENT_ID`/
  `FASTMCP_GOOGLE_CLIENT_SECRET` are real, and the full live-session OAuth
  Proxy flow was confirmed end to end for the first time — Dynamic Client
  Registration, `/authorize`, a real Google consent screen (Workspace domain
  `blumountain.me`), `/auth/callback`, token exchange, and a real
  authenticated MCP session (`POST /mcp/` returning `200`/`202`) — via MCP
  Inspector, not mocked.
- **Airtable staging base** — previously blocked: the only base the service
  account's PAT could see was "Engagement tracker," an existing business
  base unrelated to this project. Now resolved: a real, separate staging
  base was created, `ensure_schema()` provisioned all 21 tables in it for
  real, and a manually-triggered `run_staging_cycle()` staged both real test
  portals correctly — including the Enterprise-tier portal's
  `Campaigns`/`CampaignMetrics` tables and the baseline portal's graceful
  degradation on HubSpot's own account-tier gate for `CAMPAIGN`.
- **Sybill's delivery mechanism (webhook vs. polling)** — previously an open
  design question pending client clarification. Now decided: webhook, per
  the credential evidence described in blocker #1 above, not a client
  re-confirmation.
- **The live session's three tools** (`list_my_tenants`, `select_tenant`,
  `query_hubspot_data`) — previously only connecting had been confirmed, not
  actually calling them. Now resolved: exercised for real through MCP
  Inspector (including `select_tenant`'s ambiguous-name-candidates path),
  and separately covered by automated tests using a real `Client`↔`FastMCP`
  in-memory transport (`gateway/tests/session/test_live_session.py`'s
  `test_real_transport_*` tests) — not just direct Python calls with
  monkeypatched auth. **Superseded 2026-09-01**: `query_hubspot_data` is
  retired, replaced by four category-scoped tools — see the entry below.
- **Whether `pull_crm_objects()`'s `SELECT *` already returns a portal's
  custom (non-standard) HubSpot properties — genuinely unknown until
  2026-09-01.** Confirmed live against both real test portals: it does not.
  `SELECT *` returns only a small, fixed default set per object type — 5
  properties for CONTACT (`email`, `firstname`, `hs_full_name_or_email`,
  `hs_object_id`, `lastname`), 3 for COMPANY, 6 for DEAL — never a custom
  property, on either portal. This is the same class of gap as the
  `hs_object_id` finding above (HubSpot's "default set" was never
  unconditionally complete), now confirmed for custom properties
  specifically. Resolved: `get_properties`/`search_properties` were already
  on HubSpot's MCP surface (21 total tools) but silently excluded by
  `list_read_only_tools()`'s scope filter — the same class of gap that once
  hid `get_organization_details` before `IN_SCOPE_OBJECT_KEYWORDS`
  recognized it. Fixed the same way: `"propert"` added to that list.
  `HubSpotDataPullClient.discover_object_properties()` +
  `pull_crm_objects(..., properties=...)` now reach any named property.
  **Also confirmed live, and worth knowing**: explicit column selection is
  additive, not a strict narrowing — HubSpot's `query_crm_data` still
  returns its own default set alongside whatever's explicitly requested
  (confirmed: requesting `jobtitle`, absent from the default set, returned
  it populated for both sample contacts on `148997330`). No HubSpot MCP
  tool exposes an authoritative custom-vs-standard flag (a real
  `search_properties` response is only `{name, label, description}`) — the
  standard/custom distinction this project now surfaces
  (`is_custom_property_name`) is a documented heuristic (the `hs_` prefix
  is reserved; a curated known-standard set), not a certainty. See
  `openspec/changes/separate-vertical-client-agents/tasks.md` Section 5 for
  the full task-by-task record.
- **The live session's HubSpot query tool surface** — the single generic
  `query_hubspot_data` tool is retired as of 2026-09-01, replaced by four
  category-scoped tools (`query_crm_records`, `query_engagement_records`,
  `query_marketing_content`, `query_users`), each accepting an optional
  `properties` parameter. Confirmed live against `148997330` via a real
  `Client`↔`FastMCP` round trip with real (non-mocked) HubSpot pulls: all
  six tools discovered, real contact/call/user data returned, an
  out-of-category request (`query_engagement_records('contacts')`)
  correctly rejected rather than silently handled. Full interactive MCP
  Inspector re-confirmation (real Google OAuth login) is still a manual
  step for a human to run.
- Everything about the HubSpot pull itself that was previously open or
  tracked as lower-priority was already resolved as of the prior version of
  this file (the 4 marketing/analytics tool bugs, and the "teams"/"segments"/
  "landing pages"/"blog posts" observability gap) — see design.md's decision
  log.

## Available now — real work, not blocked by any of the above

Nothing currently buildable without external input remains outstanding.
Re-check this section next time the blocker picture changes.
