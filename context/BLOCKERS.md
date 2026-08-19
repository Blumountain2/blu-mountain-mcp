# Current Blockers and Available Work

What's actually blocking further progress right now, why, and what can still
be worked on in the meantime. Kept separate from `context/Hubspot/IMPLEMENTATION_PLAN.md`
(the original planning document) since that document narrates history as it
happened; this one is meant to be replaced wholesale each time the blocker
picture changes, not appended to.

Last confirmed accurate: 2026-08-17, after real, live, end-to-end
confirmation of the live session's Google OAuth Proxy (a real Google login
through MCP Inspector, full DCR/authorize/consent/token-exchange flow,
re-confirmed again via a real `/install`/`/install/mcp-auth` reinstall),
the Airtable staging pipeline (a real base created, schema provisioned via
`ensure_schema()`, and a real pull-and-stage cycle run against both test
portals), and the live session's three tools themselves (`list_my_tenants`,
`select_tenant`, `query_hubspot_data`) — exercised for real through MCP
Inspector and covered by automated real-`Client`↔`FastMCP`-transport tests,
not just connected — see
`openspec/changes/implement-hubspot-mcp-server/design.md`'s decision log for
the full history.

## Blocked (needs an external action, not resolvable by writing more code)

### 1. Real Sybill traffic — needed to validate one open edge case

**What's blocked:** Confirming task 5.6's flagged open item: whether an
ambiguous or unmatched `data.crm` reference in a real Sybill payload behaves
as expected (rejected, not guessed at) under real traffic rather than
constructed test fixtures. Also unconfirmed: the exact `crm.type` string
Sybill sends for a company/account-linked event — only `"opportunity"`
(deal-equivalent) has been confirmed live so far; `"account"` is inferred
from the same naming convention, not yet seen in a real payload.

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

## Resolved since the last version of this file

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
  monkeypatched auth.
- Everything about the HubSpot pull itself that was previously open or
  tracked as lower-priority was already resolved as of the prior version of
  this file (the 4 marketing/analytics tool bugs, and the "teams"/"segments"/
  "landing pages"/"blog posts" observability gap) — see design.md's decision
  log.

## Available now — real work, not blocked by any of the above

Nothing currently buildable without external input remains outstanding.
Re-check this section next time the blocker picture changes.
