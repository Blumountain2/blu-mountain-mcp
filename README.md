# HubSpot MCP Server

A multi-tenant data sync service for Blu Mountain's Intelligence System. It authenticates to each client's HubSpot portal, reads a defined set of read-only data, and stages it into Airtable. It also ingests Sybill call transcripts the same way.

## Status

HubSpot OAuth, the token vault, the data pull, Airtable staging, Sybill ingestion, and the live session are all built and unit-tested — 179 tests passing against a real Postgres instance, re-run automatically on every push/PR to `dev`/`main` (`.github/workflows/ci.yml`). Real HubSpot Public App and MCP Auth App credentials are registered and both installs have been completed end to end against real test portals. The live session's Google Cloud OAuth client is registered too, and a real Google login has completed the full OAuth Proxy flow end to end through MCP Inspector. Ask a teammate for the current phase plan and project background if you need it.

## What this is

- One shared HubSpot Public App, using OAuth v3 with PKCE. Each client authorizes it separately into their own HubSpot portal, producing an isolated token set per client.
- A second, separate shared credential, the HubSpot MCP Auth App (spec Section 4.1), installed into the same portal right after the Public App — HubSpot's remote MCP endpoint (`mcp.hubspot.com`) is its own OAuth resource server and doesn't accept the Public App's token.
- A Postgres-backed vault stores each client's tokens (both credentials above, in separate tables), encrypted at rest, refreshed automatically before expiry.
- A scheduled job pulls read-only HubSpot data per client and writes normalized, client-tagged records into Airtable.
- A webhook receiver ingests Sybill call transcripts and stages those into Airtable the same way.
- This service also hosts a live, interactive MCP server: Blu Mountain staff connect from Claude Desktop, Claude Code, or Claude Cowork as an MCP client, authenticate through Google Workspace via FastMCP's own OAuth Proxy (not a third-party identity broker), select exactly one client tenant, and get a live read-only response back. Both this and the scheduled Airtable staging job share the same tenant token vault.
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
3. Register the HubSpot Public App via the CLI (`hs project create` with an OAuth-auth scaffold, `hs project upload` to build and deploy it). Set its redirect URI to match `HUBSPOT_REDIRECT_URI` in `.env`, and put the resulting client ID and secret in `.env` as `HUBSPOT_APP_CLIENT_ID`/`HUBSPOT_APP_CLIENT_SECRET`.
4. Register the HubSpot MCP Auth App (spec Section 4.1) — a separate app, under "MCP Auth Apps" in the same developer account, installed into the same portal after step 3. Set its redirect URI to match `HUBSPOT_MCP_REDIRECT_URI` in `.env`, and put the resulting client ID and secret in `.env` as `HUBSPOT_MCP_CLIENT_ID`/`HUBSPOT_MCP_CLIENT_SECRET`.
5. Register a Web application OAuth 2.0 client in Google Cloud Console for the live session. Set its redirect URI to match `FASTMCP_OAUTH_REDIRECT_URI` in `.env` (defaults to `http://localhost:8888/mcp/auth/callback`), and put the resulting client ID and secret in `.env` as `FASTMCP_GOOGLE_CLIENT_ID`/`FASTMCP_GOOGLE_CLIENT_SECRET`. Make sure `FASTMCP_BASE_URL` includes the `/mcp` mount path (e.g. `http://localhost:8888/mcp`) — FastMCP has no other way to know its own external path.
6. Start the stack:
   ```bash
   docker-compose up -d
   ```
7. Check health:
   ```bash
   curl http://localhost:8888/health
   ```
8. Complete both HubSpot installs against the running stack, in order: visit `/install` (Public App), then `/install/mcp-auth` (MCP Auth App) — the second depends on the first having already created a `tenants` row for that portal, and returns `409` with an explicit message if run out of order. See `context/ONBOARDING_RUNBOOK.md` for the full flow.

## Project structure

```
├── gateway/
│   ├── main.py            # service entrypoint: routes, scheduler, FastMCP mount
│   ├── config.py          # centralized environment configuration
│   ├── db.py              # Postgres pool + schema bootstrap
│   ├── schema.sql         # Postgres schema (tenants, tokens, audit log, etc.)
│   ├── auth/              # HubSpot OAuth, token vault, crypto, security
│   ├── sync/              # HubSpot data-pull client + Airtable staging job
│   ├── webhooks/          # Sybill webhook receiver
│   ├── session/           # live interactive session (FastMCP OAuth Proxy) + direct staff auth
│   ├── tests/             # mirrors the subpackage layout above
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── pytest.ini
│   └── Dockerfile
├── docker-compose.yml     # mcp-gateway service + Postgres
├── scripts/
│   └── test_all.py        # end-to-end smoke test script
└── .env.example
```