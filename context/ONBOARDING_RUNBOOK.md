# Onboarding Runbook

Covers the two onboarding actions this system has: connecting a new client's HubSpot portal (Flow B), and restricting a staff member from a tenant in the live session (Flow A) — access itself is default-open and needs no per-staff step. Each is independent of the other — connecting a client portal does not require any staff onboarding step, and vice versa.

## 1. Connecting a new client's HubSpot portal (Flow B)

Two separate installs, in this order — the second depends on the first
having already run for the same portal (`mcp_tokens.hub_id` references
`tenants(hub_id)`, which only the first install creates).

### 1a. Public App install (required first)

The OAuth v3 + PKCE install flow (`gateway/auth/hubspot_oauth.py`),
authorizing Blu Mountain's one shared HubSpot Public App into that client's
portal. It grants portal-level, read-only access — no per-user HubSpot login
is involved.

**Prerequisites (one-time, not per-client):**

- The HubSpot Public App must already be registered (`HUBSPOT_APP_CLIENT_ID`,
`HUBSPOT_APP_CLIENT_SECRET`, `HUBSPOT_REDIRECT_URI` set in the environment).
- The service must be reachable at `HUBSPOT_REDIRECT_URI` for HubSpot to
redirect back to after the portal admin approves.

**Steps, per client:**

1. Send the client's portal admin (whoever can approve app installs on that
  HubSpot portal) to `GET /install` on the service. This redirects them to
   HubSpot's own authorization screen, listing exactly the read-only scopes
   in `HUBSPOT_SCOPES` — nothing else, per this project's read-only-absolute
   rule.
2. The portal admin reviews and approves the install on HubSpot's side. No
  credentials are shared with Blu Mountain directly; the admin never sees or
   hands over a password or API key.
3. HubSpot redirects back to `GET /callback` with an authorization code.
  The service exchanges it for a token pair, looks up the portal's `hub_id`
   (`GET /oauth/v1/access-tokens/{token}`, since HubSpot's token exchange
   response doesn't include it), creates the `tenants` row, and vaults the
   encrypted token pair keyed by that `hub_id`.
4. A successful callback shows the portal admin a plain success page
  (`auth/pages.py`, not raw JSON — the real caller here is a browser, not a
   script) with a button straight to step 1b below, and is recorded in
   `audit_log` as `hubspot_install_completed`. The `hub_id` shown on that
   page is what every later step — Flow B's second install below, the
   scheduled sync, the live session's tenant selection — refers to this
   client by.

### 1b. MCP Auth App install (required second, same portal)

A separate app (spec Section 4.1, `gateway/auth/mcp_auth.py`) — HubSpot's
remote MCP endpoint (`mcp.hubspot.com`) does not accept the Public App's
CRM-scoped token, so this is a second, independent credential, installed
into the same portal the same way.

**Prerequisites:** `HUBSPOT_MCP_CLIENT_ID`, `HUBSPOT_MCP_CLIENT_SECRET`,
`HUBSPOT_MCP_REDIRECT_URI` set in the environment (a separate app,
registered under "MCP Auth Apps" in the HubSpot developer account, not the
same app as 1a).

**Steps, per client, after 1a has completed for this same portal:**

1. Send the same portal admin to `GET /install/mcp-auth`. Redirects to
   `mcp.hubspot.com`'s own authorization screen (a distinct host from
   `app.hubspot.com` — this app is its own OAuth resource server). This
   screen presents a per-object permission choice — **"View Only"/"View
   All"**, **"All"**, or **"None"** — and the admin must choose the
   read-only option. This project's own code enforces read-only regardless
   (see `sync/hubspot_client.py`'s read-verb allowlist and SQL-shape
   guard), but choosing "All" here would additionally grant real write
   access at the HubSpot permission layer itself, one more reason to get
   this right at install time rather than relying on the code alone.
2. Admin approves. HubSpot redirects back to `GET /callback/mcp-auth`,
   which exchanges the code — the token response body itself carries
   `hub_id` directly (confirmed against a real install; unlike the Public
   App, no separate lookup call is needed) — and vaults the pair into
   `mcp_tokens`.
3. If step 1a was skipped for this portal, this shows a "One Step Missing"
   page (`409`) with a link straight back to `/install` — complete 1a
   first, then retry 1b.
4. Confirm both installs are live: the next scheduled sync cycle
   (`SYNC_INTERVAL_MINUTES`) should pick up the new `hub_id` and stage its
   data into Airtable without any separate registration step — the sync job
   iterates whatever tenants exist in `tenants`, nothing needs to be added
   to a separate list by hand. If only 1a completed, the sync will find the
   tenant but fail to reach `mcp.hubspot.com` for it (`mcp_tokens` has no row
   yet) — check `hubspot_pull.tool_failed`-style log lines if data isn't
   showing up.

**What can go wrong:**

The admin sees a plain "Link Expired"/"Connection Failed" page for any of
these (`auth/pages.py`), with a Start Over link back to the right step —
not a raw error code, though the same detail is still logged server-side:

- `state_mismatch` (403 on callback): the admin took longer than 10 minutes
between hitting `/install` and approving, or reused a stale link. Just have
them start over at `/install`.
- A HubSpot OAuth error on callback (400, with HubSpot's own `error` code):
logged with the error code only, never token values. Check the error code
against HubSpot's own OAuth error reference.



## 2. Staff access to tenants in the live session (Flow A) — default-open

There is no onboarding step for the common case. Any staff member whose
Google Workspace account is on the allowed domain
(`FASTMCP_ALLOWED_GOOGLE_DOMAINS`) automatically has access to every
installed tenant the moment they sign in — nothing to insert, nothing to
configure, no Postgres access needed. `list_my_tenants()` reflects every
installed tenant immediately for a brand-new staff member with zero setup.

**If a specific client needs to be walled off from a specific staff member**
(e.g. a confidentiality requirement), that's the one case that needs a
Postgres row, in `staff_tenant_restrictions` — a deny-list, not a grant
list:

1. Insert a restriction:
   ```sql
   INSERT INTO staff_tenant_restrictions (staff_identity, hub_id)
   VALUES ('person@bludomain.com', '<hub_id from Flow B step 4>');
   ```
   `staff_identity` is the email claim from their Google token. Casing
   doesn't matter here — the comparison is case-insensitive on both sides,
   so typing it in any casing still blocks the intended person. `hub_id`
   must be a real, currently-or-previously-installed tenant (it references
   `tenants`); a mistyped `hub_id` fails the insert outright rather than
   silently becoming a no-op restriction. This staff member keeps default
   access to every *other* installed tenant; only this one `hub_id` is
   blocked for them.
2. Effective immediately: their session's `_permitted_tenants` reads this
   table live, no cache to invalidate. Any of their sessions that had
   already selected that tenant (`live_session_selection`) will get
   `TenantNotPermitted` on their next query, not silently continue working.
3. Removing a restriction is the same operation in reverse: `DELETE FROM
   staff_tenant_restrictions WHERE staff_identity = ... AND hub_id = ...`.
   That staff member reverts to default access for that tenant on their next
   query — no other step needed.

If a staff member ends up with access to more than one tenant (the normal
case once more than one client is connected), they must call
`select_tenant(hub_id)` once per session before `query_hubspot_data` returns
anything — this is enforced, not optional, regardless of whether that access
came from being unrestricted (the default) or would have come from an
explicit grant under the old model.

**Auditing:** every tenant selection and every query is recorded in
`audit_log` by `staff_identity` and `hub_id` — this is the only record tying
a HubSpot read back to a specific person, so no separate access log needs to
be maintained by hand.

## 3. `session/staff_auth.py` — not part of onboarding

Kept in the codebase but unhooked from `main.py`; there's nothing to onboard
here since it has no active consumer. See `design.md`'s decision log
(`implement-hubspot-mcp-server`) for why it exists and what would need to be
true for it to matter — if a future non-MCP consumer is ever built against
it, that's when this section gets real steps, not before.