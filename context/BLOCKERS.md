# Current Blockers and Available Work

What's actually blocking further progress right now, why, and what can still
be worked on in the meantime. Kept separate from `context/Hubspot/IMPLEMENTATION_PLAN.md`
(the original planning document) since that document narrates history as it
happened; this one is meant to be replaced wholesale each time the blocker
picture changes, not appended to.

Last confirmed accurate: 2026-08-13, after a real, live, end-to-end HubSpot
install and full data pull against two test portals — see
`openspec/changes/implement-hubspot-mcp-server/design.md`'s decision log for
the full history of what that confirmed, including every previously-open
gap in the HubSpot pull itself now being resolved.

## Blocked (needs an external action, not resolvable by writing more code)

### 1. Google Cloud OAuth client for the live session — blocked, manual

**What's blocked:** Real end-to-end testing of the live MCP session (FastMCP's
OAuth Proxy wrapping Google Workspace) — a Blu Mountain staff member actually
connecting from Claude Desktop/Code/Cowork, signing in, and getting a live
HubSpot response back.

**Why:** `FASTMCP_GOOGLE_CLIENT_ID`/`FASTMCP_GOOGLE_CLIENT_SECRET` need a real
Web application OAuth 2.0 client registered in a Google Cloud project (Google
does not support automatic client registration). Nobody has provisioned this
yet.

**What's NOT blocked by this:** everything else about the live session is
built and unit-tested (domain allowlisting, default-open tenant access with
explicit restrictions, tenant-selection enforcement, per-access audit
logging, the two discovery-metadata redirect fixes) — see tasks.md Section 6,
items 6.2-6.11, all `[x]`. Only 6.1 (the credential itself) and the live
connect it enables remain open.

**Who unblocks it:** whoever has (or can get) admin access to a Google Cloud
project for Blu Mountain.

**Request to send:** *"We need a Google Cloud OAuth 2.0 'Web application'
client so Blu Mountain staff can sign into the live HubSpot MCP session with
Google Workspace. To set this up: in a Google Cloud project, create an OAuth
2.0 Client ID (type: Web application), set its redirect URI to
`http://localhost:8888/mcp/auth/callback` (we'll update this once hosting
exists), and send us the resulting Client ID and Client Secret."*

### 2. Airtable staging base — confirmed it needs creating, not just confirming

**What's blocked:** Re-running task 4.6's real end-to-end staging test (pull
real HubSpot CRM data → normalize → write into a real Airtable base, tagged
by client) — currently only proven against a fake Airtable API.

**Why:** Checked directly via Airtable's own metadata API
(`GET /v0/meta/bases`) — the current `AIRTABLE_API_KEY` PAT can see exactly
one base, "Engagement tracker" (`appuhahB1CTVY0nyF`), and it is **not** a
staging base: it's an existing, actively-used business base (one table per
real client, meeting/task/QA tracking), unrelated to this project's
per-HubSpot-object-type staging schema. Writing this sync job's tables into
it risks colliding with real business data already there. No staging base
exists yet, and this PAT has no visibility into any other base or workspace
to create one from.

**What's NOT blocked by this:** the staging code itself — schema design,
per-object-type normalization, the scheduled job, client tagging, and
cross-tenant isolation — is fully built and unit-tested (tasks.md Section 4,
items 4.1-4.5, all `[x]`).

**Who unblocks it:** whoever manages the `internalops@blumountain.me`
Airtable account.

**Request to send:** *"We need a new, empty Airtable base to stage HubSpot
and Sybill data into — separate from the existing 'Engagement tracker' base,
which is already in use for something else. To set this up: create a new
base in Airtable, share it with the `internalops@blumountain.me` service
account at Creator access, and send us that base's ID (starts with `app...`
— found in the base's URL or its API documentation page)."*

### 3. Real Sybill traffic — needed to validate one open edge case

**What's blocked:** Confirming task 5.6's flagged open item: whether an
ambiguous or unmatched `crmInfo.accountId`/`opportunityId` in a real Sybill
payload behaves as expected (rejected, not guessed at) under real traffic
rather than constructed test fixtures.

**Why:** This needs an actual Sybill webhook delivery hitting the receiver,
which needs Sybill actually configured to send them for a real client
account.

**What's NOT blocked by this:** signature validation, normalization, and
staging are all built and unit-tested against Sybill's own published schema
(tasks.md Section 5, items 5.1-5.6, all `[x]`). This is a real-traffic
validation step, not missing functionality.

**Who unblocks it:** whoever manages the Sybill integration on Blu Mountain's
side, once at least one client has both Sybill and this system live. No
request to send yet — nothing to ask for until a real client is live on
both.

### 4. Production hosting, subdomain, managed Postgres, secrets platform

**What's blocked:** Deploying anywhere other than a local machine.

**Why:** No subdomain/DNS/TLS, managed Postgres instance, or production
secrets platform has been provisioned yet (`context/Hubspot/IMPLEMENTATION_PLAN.md`
Section 4.5). Production OAuth redirect URIs for both HubSpot and Google
can't be registered until the subdomain exists.

**What's NOT blocked by this:** all local development, testing, and the real
credentialed HubSpot testing already done. This only matters once onboarding
a real (non-test) client portal becomes the goal.

**Who unblocks it:** whoever can create/delegate the hosting account.

**Request to send:** *"We need a subdomain (e.g. `mcp.blumountain.com`) with
DNS and TLS, a managed Postgres instance, and a decision on a
secrets-management platform before this can run anywhere but a local
machine. To set this up: confirm the hosting account (Hostinger was the
original recommendation) and delegate admin access to Gumpper Group — or let
us know if a different host is preferred."*

## Resolved since the last version of this file

Everything about the HubSpot pull itself that was previously open or
tracked as lower-priority is now done and confirmed live:

- The 4 marketing/analytics tools that originally failed
  (`get_campaign_attribution_reports`, `get_content_analytics_report`,
  `get_marketing_email_analytics`, `read_campaign_data`) are all fixed and
  confirmed working. Two were genuine missing-parameter bugs; the other two
  needed a second, Enterprise-tier developer test account (`hub_id=149094230`,
  free — HubSpot's test accounts include a 90-day enterprise trial by
  default and can't be upgraded, so a fresh account was the fix, not an
  upgrade) with a real campaign created in it to verify.
- A full audit of every real discovered tool (not just the ones already
  failing) found and fixed a real observability gap, and through it, real
  coverage for the spec's "teams," "segments," "landing pages," and "blog
  posts" reference objects.
- See `openspec/changes/implement-hubspot-mcp-server/design.md`'s decision
  log for the full detail on all of the above.

## Available now — real work, not blocked by any of the above

Nothing outstanding as of this version. Everything currently buildable
without external input has been built; what remains is either genuinely
blocked (above) or not yet identified. Re-check this section next time the
blocker picture changes.
