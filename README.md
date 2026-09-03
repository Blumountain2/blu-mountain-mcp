# HubSpot MCP Server

A multi-tenant data sync service for Blu Mountain's Intelligence System. It authenticates to each client's HubSpot portal, reads a defined set of read-only data, and stages it into Airtable. It also ingests Sybill call transcripts the same way.

## Status

HubSpot OAuth, the token vault, the data pull, Airtable staging, Sybill ingestion, and the live session are all built and unit-tested — 306 tests passing against a real Postgres instance, re-run automatically on every push/PR to `dev`/`main` (`.github/workflows/ci.yml`). HubSpot access reads the plain REST API (`api.hubapi.com`) directly with the Public App's own token — the MCP Auth App and `mcp.hubspot.com` are no longer part of this project at all (see `CLAUDE.md`'s Data pull section). A real HubSpot Public App credential is registered and installed end to end against real test portals. The live session's Google Cloud OAuth client is registered too, and a real Google login has completed the full OAuth Proxy flow end to end through MCP Inspector. Ask a teammate for the current phase plan and project background if you need it.

## What this is

- One shared HubSpot Public App, using OAuth v3 with PKCE. Each client authorizes it separately into their own HubSpot portal, producing an isolated token set per client — the single install step for a new client.
- A Postgres-backed vault stores each client's token, encrypted at rest, refreshed automatically before expiry.
- A scheduled job pulls read-only HubSpot data per client and writes normalized, client-tagged records into Airtable.
- A webhook receiver ingests Sybill call transcripts and stages those into Airtable the same way.
- This service also hosts a live, interactive MCP server: Blu Mountain staff connect from Claude Desktop, Claude Code, or Claude Cowork as an MCP client, authenticate through Google Workspace via FastMCP's own OAuth Proxy (not a third-party identity broker), select exactly one client tenant, and query real HubSpot data through four category-scoped tools (`query_crm_records`, `query_engagement_records`, `query_marketing_content`, `query_users`), each able to reach a portal's custom fields, not just HubSpot's own default property set. Both this and the scheduled Airtable staging job share the same tenant token vault.
- On top of the pull/staging layer: a two-tier AI agent system (`gateway/frameworks/`) — one independently-editable agent template per business vertical, and one persisted agent instance per client built from its vertical's template plus that client's own confirmed-relevant HubSpot fields. Gathers data only, via a Claude API tool-use loop restricted to the same read-only allowlisted pull paths everything else in this project uses — never analysis, never a trained/fine-tuned model.
- A debug HTTP API (`gateway/debug_api.py`, `/debug/hubspot/*`) for pulling a real installed tenant's HubSpot data directly via Postman — gated by `DEBUG_API_KEY`, since the `/mcp` mount can't be exercised with plain HTTP requests. See `postman/blu-mountain-mcp.postman_collection.json`.
- HubSpot access is read-only everywhere. Airtable is the only read-write integration in this system.

## Prerequisites

- Docker and Docker Compose (recommended, matches the container's Python version exactly)
- Or Python 3.11+ if running outside Docker
- The HubSpot CLI (`npm install -g @hubspot/cli`, then `hs init`) and a HubSpot Developer account with a test/sandbox portal — public app creation through the legacy developers.hubspot.com UI is disabled; apps are now created via the CLI's Developer Projects framework (`hs project create`)
- A Google Cloud project, to register a Web application OAuth 2.0 client for the live session's FastMCP OAuth Proxy (Google Workspace sign-in for staff)

## Setup

1. Copy the environment template and fill in real values:
   ```bash
   cp .env.example .env
   ```
2. Generate an app-level encryption key and put it in `.env` as `APP_ENCRYPTION_KEY`:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. Register the HubSpot Public App via the CLI (`hs project create` with an OAuth-auth scaffold, `hs project upload` to build and deploy it). Set its redirect URI to match `HUBSPOT_REDIRECT_URI` in `.env`, and put the resulting client ID and secret in `.env` as `HUBSPOT_APP_CLIENT_ID`/`HUBSPOT_APP_CLIENT_SECRET`. `HUBSPOT_SCOPES`/`HUBSPOT_OPTIONAL_SCOPES` in `.env` must match `hubspot-app/src/app/app-hsmeta.json`'s own `requiredScopes`/`optionalScopes` declaration — HubSpot validates against the app's own registered manifest regardless of which request param a scope is sent under, so the two must be edited together.
4. Register a Web application OAuth 2.0 client in Google Cloud Console for the live session. Set its redirect URI to match `FASTMCP_OAUTH_REDIRECT_URI` in `.env` (defaults to `http://localhost:8888/mcp/auth/callback`), and put the resulting client ID and secret in `.env` as `FASTMCP_GOOGLE_CLIENT_ID`/`FASTMCP_GOOGLE_CLIENT_SECRET`. Make sure `FASTMCP_BASE_URL` includes the `/mcp` mount path (e.g. `http://localhost:8888/mcp`) — FastMCP has no other way to know its own external path.
5. Start the stack:
   ```bash
   docker-compose up -d
   ```
6. Check health:
   ```bash
   curl http://localhost:8888/health
   ```
7. Complete the HubSpot install against the running stack: visit `/install`. See `context/ONBOARDING_RUNBOOK.md` for the full flow.

## Project structure

```
├── gateway/
│   ├── main.py            # service entrypoint: routes, scheduler, FastMCP mount
│   ├── config.py          # centralized environment configuration
│   ├── db.py              # Postgres pool + schema bootstrap
│   ├── debug_api.py       # API-key-gated /debug/hubspot/* HTTP surface for Postman
│   ├── schema.sql         # Postgres schema (tenants, tokens, audit log, etc.)
│   ├── auth/              # HubSpot OAuth, token vault, crypto, security
│   ├── sync/              # HubSpot data-pull client + Airtable staging job
│   ├── webhooks/          # Sybill webhook receiver
│   ├── session/           # live interactive session (FastMCP OAuth Proxy) + direct staff auth
│   ├── frameworks/        # shared vertical frameworks, tenant profiling/onboarding,
│   │                      # per-vertical agent templates, per-client agent instances
│   ├── scripts/
│   │   └── live_verification.py  # non-mocked check against real Postgres/HubSpot/Anthropic
│   ├── tests/             # mirrors the subpackage layout above
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── pytest.ini
│   └── Dockerfile
├── docker-compose.yml     # mcp-gateway service + Postgres
├── scripts/
│   └── test_all.py        # end-to-end smoke test script (real CI entry point)
├── postman/
│   └── blu-mountain-mcp.postman_collection.json  # this service's own HTTP endpoints
└── .env.example
```