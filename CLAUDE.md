# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What this project is

A multi-tenant HubSpot data sync service for Blu Mountain's Intelligence System. It authenticates to each client's HubSpot portal (one shared HubSpot Public App, OAuth v3 with PKCE, installed separately into each client), reads a defined set of read-only HubSpot data per client, and stages normalized, client-tagged copies of it into Airtable. It also ingests Sybill call transcripts via webhook and stages those the same way.

A scheduled batch job pulls HubSpot data per tenant and stages it into Airtable, which analysis jobs and dashboards read from. Separately, a live, interactive MCP session lets Blu Mountain staff connect through Claude Desktop, Claude Code, or Claude Cowork — identically from any of the three — authenticate via Google Workspace, and query one selected client's HubSpot data live. This is built with FastMCP's own OAuth Proxy wrapping a Google Workspace OAuth client, not WorkOS, WorkOS is no longer part of this project. A separate direct Google/Microsoft JWT verification path also exists (`gateway/session/staff_auth.py`), but is not wired into `main.py`: no planning document ever identified a consumer for it distinct from what the live session already does, so it's kept in the codebase, unhooked, in case a future non-MCP consumer (e.g. a web dashboard) needs it. See the implementation plan and design.md's decision log. Ask a teammate for the current phase plan and additional architecture detail if you need it.

## Current build state

HubSpot OAuth, the token vault, the data pull, Airtable staging, Sybill ingestion, and the live session are now all built, organized into `auth/`, `sync/`, `webhooks/`, and `session/` subpackages under `gateway/` (plus `main.py`, `config.py`, `db.py`, and `schema.sql` at the root). All 144 tests pass (`pytest tests/` inside the container, run against a real Postgres instance via `docker compose`), and `docker compose up` serves `/health`, `/`, and the live session's `/mcp` mount correctly, checked by actually sending requests, not just reading the code. `/staff/me` no longer exists: `session/staff_auth.py` is kept in the codebase but unhooked from `main.py`, see the Architecture section below.

The HubSpot side is now verified end-to-end against real external credentials, not just mocked ones: a real HubSpot Public App and a real HubSpot MCP Auth App (spec Section 4.1) are both registered, and both installs (`/install`, `/install/mcp-auth`) have completed for real against two test portals (see the Data pull section below), followed by real data pulls (`query_crm_data` against `mcp.hubspot.com`) that returned real records matching each portal's known state. The live session's FastMCP OAuth Proxy remains unverified end-to-end: it still needs a real Google Cloud OAuth client, which is not provisioned yet. Until that exists, no staff member can connect through the live session for real. Check the actual module contents before assuming something is or isn't implemented — this file is a summary, not the source of truth.

## Non-negotiables

These apply to every commit and every file in this repository.

- No celebratory or aspirational status claims. State only what was actually run and what actually passed.
- HubSpot access is read-only, absolutely. No write scopes, no write code paths, ever. Airtable is the only read-write integration in this system.
- Any multi-tenant code path needs an isolation test proving no cross-tenant data or error leakage before it's considered done.

## Architecture (target, per the implementation plan)

**Onboarding and token vault**:
- `/install` and `/callback` routes handle the OAuth v3 + PKCE flow for a client portal.
- Tokens are stored in Postgres, keyed by `hub_id` (portal-level authorization, not per-user), AES-256 encrypted with a per-tenant key derived from a single root key (`APP_ENCRYPTION_KEY`) via HKDF, using `hub_id` as derivation context. No tenant's key is ever derivable from another tenant's data.
- Tokens refresh proactively on a five-minute buffer, serialized per tenant via Postgres advisory locks so multiple instances never race to refresh the same tenant.
- `/callback` and `/callback/mcp-auth` render styled HTML pages (`auth/pages.py`), not raw JSON — the actual caller is a portal admin's browser at the end of HubSpot's consent redirect, not a programmatic client. Success pages show the next step's absolute URL as a clickable link plus a button; error pages (all 7 paths across both callbacks) show a plain-language message and a retry link. Both derive the current URL from the incoming request's own host, so they're correct in any environment without code changes.

**Data pull**:
- A per-tenant client (`sync/hubspot_client.py::HubSpotDataPullClient`) reads HubSpot's remote MCP endpoint (`mcp.hubspot.com`) using a vaulted MCP Auth App token. Three distinct read paths, all confirmed live, not assumed from the spec's object list:
  1. **Generic per-object tools** (marketing/analytics tools, e.g. `search_owners`, `get_user_details`, `get_organization_details`), discovered dynamically via `list_tools()`. A tool is only called if its name matches a recognized read verb AND contains no recognized write verb (`_is_read_safe`) — an allowlist, not just a write-verb blocklist, since the `tickets` scope carries real write capability at the OAuth level (HubSpot has no read-only-only Tickets scope) and this filter is the actual enforcement for that object, not a defensive extra. `list_read_only_tools()` logs every excluded tool in one of three buckets (write-shaped, unrecognized, out-of-scope) — the third bucket used to log nothing at all, which is exactly how `get_organization_details` (the real path to the spec's "teams" object) went unnoticed for a while. Some of these tools need a fixed default parameter their own schema requires but never anything caller-supplied (`_DEFAULT_TOOL_PARAMS`), confirmed live for `get_content_analytics_report`, `get_marketing_email_analytics`, and `get_campaign_attribution_reports`.
  2. **The core CRM object set** (contacts, companies, deals, tickets, line items, products, calls, emails, meetings, notes, tasks, plus segments/landing pages/blog posts/campaigns) has no per-object tool at all — confirmed live, the only way to read any of it is `query_crm_data`, one generic tool taking a raw SQL-like string (HubSpot's own constrained dialect: no JOIN/UNION/subqueries/aliases). `pull_crm_objects()` handles this separately: SQL is always a fixed `SELECT * FROM {TYPE}` authored in code from `CRM_OBJECT_TYPES` (real names confirmed via `discover_hubspot_schema`, e.g. `MEETING_EVENT` not `MEETING`, `OBJECT_LIST` for "segments"), never from caller input, and still checked by `_is_safe_select()` (rejects anything but a single plain `SELECT`) as defense in depth. `CAMPAIGN`'s `readAccess` is gated per-portal by HubSpot's own account tier (`REQUIRES_ACCOUNT_MODIFICATION` on a non-Enterprise account) — degrades gracefully (`pull_failed`, not a crash) rather than assuming every portal has it.
  3. **Per-campaign metrics** via `read_campaign_data` — every one of its operations needs a specific `campaignCrmObjectId`, so there's no single fixed default the way path 1's tools have. `pull_campaign_data()` enumerates real campaign IDs via `query_crm_data` first, then calls once per campaign; excluded from path 1's generic loop (`PER_ITEM_TOOLS`, public so `session/live_session.py`'s interactive query tool excludes it the same way) since its name would otherwise pass the filter and always fail there with no ID supplied.
  - **None of HubSpot's real MCP tools declare an `outputSchema`** — confirmed live across all 20 discovered tools. The real payload is always JSON text inside `result.content`, never FastMCP's `result.data` (`hubspot_client.py::_extract_result`/`_unwrap_query_crm_data` — the latter specifically for `query_crm_data`'s own citation-style envelope, distinct from other tools' plain JSON).
  - Two developer test portals exist for exercising this: `hub_id=148997330` (baseline) and `hub_id=149094230` (Enterprise tier, with a real campaign, for the account-tier-gated tools). Both are free — HubSpot's developer test accounts include a 90-day enterprise-feature trial by default and cannot be upgraded, so a fresh account is the way to test a different tier, not an upgrade.
- The MCP Auth App (spec Section 4.1) is a separate credential from the Public App above — confirmed live that `mcp.hubspot.com` is its own OAuth resource server (its own RFC 9728/8414 metadata, its own `oauth/v3/token` endpoint under that host) and does not accept the Public App's CRM-scoped token. Same shape as the Public App otherwise: one shared Client ID/Secret, installed once per tenant, vaulted per-tenant token (`mcp_tokens`, separate from `tokens`), same PKCE + refresh-token mechanics. `auth/mcp_auth.py` and `/install/mcp-auth` + `/callback/mcp-auth` mirror `auth/hubspot_oauth.py` deliberately, kept as a separate module so neither install flow's code risks the other. `hub_id` for this app comes directly from the token-exchange response body, confirmed live — its introspection endpoint (`/oauth/v3/token/introspect`) returns only RFC 7662's minimal `{"active": true/false}`, no portal identifier, so it's not used for anything.
- This pull capability is shared infrastructure: both the scheduled job and the live session use it identically, it doesn't decide who's allowed to call it.
- A scheduled job (APScheduler) drives the pull-and-stage cycle on an interval (`SYNC_INTERVAL_MINUTES`).

**Live interactive session** (active, built with FastMCP's OAuth Proxy, not WorkOS):
- FastMCP's OAuth Proxy wraps one manually registered Google Workspace OAuth client, presenting a Protected Resource Metadata-serving, DCR-compliant interface to Claude Desktop/Cowork/Code, so the "Connect" experience works the same way it would for any other remote MCP server.
- It issues its own audience-scoped JWT to the connecting client rather than forwarding Google's token, this is what satisfies the no-token-passthrough requirement, Google's token never leaves the proxy.
- Enforces the Google Workspace domain allowlist on every login, rejecting sign-ins from outside it.
- Tenant access is default-open, not an allow-list: any staff member who signs in successfully has access to every installed tenant, unless a row in `staff_tenant_restrictions` explicitly restricts them from a specific one. A session with more than one permitted tenant must have exactly one selected before any data is returned. See design.md's decision log for why this replaced an earlier allow-list design.
- Every interactive access is audited by staff identity and tenant, this is the only record that can attribute a HubSpot read to a specific person, since HubSpot itself only sees the shared app credential.
- `main.py` has two redirect routes compensating for discovery URLs that don't resolve correctly given the outer `/mcp` mount: the RFC 9728 protected-resource metadata, and the RFC 8414 authorization-server metadata's standard discovery path. See design.md's decision log for the full mechanism. Both confirmed fixed end to end against a real MCP Inspector session, independent of the still-pending Google credentials below.
- Decided: Google only. Microsoft 365 OAuth Proxy parity was considered and explicitly not built for the live session; see design.md's decision log. This doesn't affect `staff_auth.py` below, which keeps its own separate Google/Microsoft support unchanged.

**Direct Google/Microsoft JWT verification** (kept, unhooked, not currently wired to anything):
- `gateway/session/staff_auth.py` verifies an already-issued Google or Microsoft token directly, a plain API guard, not an MCP server. Enforces `GOOGLE_HOSTED_DOMAIN`.
- Built before the live session's FastMCP OAuth Proxy path was understood as buildable. No planning document ever identified a distinct consumer for it, so `main.py` no longer routes to it (`/staff/me` doesn't exist). Kept in the codebase in case a future non-MCP consumer (e.g. a web dashboard) needs a plain bearer-token verifier; import `session.staff_auth` directly if so. Do not wire it back into `main.py` without a concrete reason to.

**Staging**:
- Normalized HubSpot data and Sybill call transcripts are written into Airtable via `pyairtable`, every record tagged by client.
- The Sybill webhook receiver validates payload signatures (HMAC, Svix-style) and rejects stale or unsigned requests before staging.

**Security controls**:
- Per-tenant rate limiting via a Postgres token-bucket table, no Redis.
- Per-tenant audit log in Postgres: every pull, who, what, when, which client, minimum 60 day retention.
- No credentials in logs, prompts, or tool descriptions, ever.

## Development commands

```bash
# Copy the environment template and fill in real values
cp .env.example .env

# Generate the app-level token encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Start the stack (Postgres + the service)
docker-compose up -d

# Check service health
curl http://localhost:8888/health

# Local development without Docker (requires Python 3.11+ to match the container)
cd gateway && pip install -r requirements.txt

# Run the full test suite (rebuild first if source changed since the last image build)
docker compose build mcp-gateway
docker compose run --rm --user 0 mcp-gateway sh -c "pip install -q -r requirements-dev.txt && pytest -q"
```

The test suite runs against its own `mcp_test` Postgres database, never the same `mcp` database `docker compose up`'s dev stack uses — `gateway/tests/conftest.py`'s `_pool` fixture truncates every table it touches after each test, and running it against `mcp` directly destroyed a real, verified tenant install twice in one session before this was fixed. `mcp_test` is created automatically on first run (via a maintenance connection to Postgres's own `postgres` database), nothing to set up by hand.

## Configuration

Environment variables are defined in `.env.example`. Key groups:
- HubSpot Public App OAuth (Flow B): `HUBSPOT_APP_CLIENT_ID`, `HUBSPOT_APP_CLIENT_SECRET`, `HUBSPOT_REDIRECT_URI`, `HUBSPOT_SCOPES`
- HubSpot MCP Auth App (spec Section 4.1, separate credential for mcp.hubspot.com): `HUBSPOT_MCP_CLIENT_ID`, `HUBSPOT_MCP_CLIENT_SECRET`, `HUBSPOT_MCP_REDIRECT_URI`
- Postgres: `DATABASE_URL` and its component parts
- Token encryption: `APP_ENCRYPTION_KEY`
- Airtable: `AIRTABLE_SERVICE_ACCOUNT`, `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`
- Sybill: `SYBILL_WEBHOOK`
- Direct Google/Microsoft (separate surface, `session/staff_auth.py`, kept but unhooked from `main.py`): `GOOGLE_CLIENT_ID`, `GOOGLE_HOSTED_DOMAIN`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_TENANT_ID` — no client secret for either provider, this path only verifies already-issued JWTs (audience + provider JWKS), it never exchanges a code

FastMCP OAuth Proxy variables (`FASTMCP_GOOGLE_CLIENT_ID`, `FASTMCP_GOOGLE_CLIENT_SECRET`, `FASTMCP_BASE_URL`, `FASTMCP_OAUTH_REDIRECT_URI`, `FASTMCP_ALLOWED_GOOGLE_DOMAINS`, `FASTMCP_ACCESS_TOKEN_TTL_MINUTES`) are in `.env.example` now, but the real Google Cloud OAuth client they'd hold values for is not provisioned yet, tracked in the implementation plan's Section 4.3. WorkOS has been fully removed — no `WORKOS_*` variables remain anywhere in this project.


