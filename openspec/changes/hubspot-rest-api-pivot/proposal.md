## Why

This project's entire HubSpot data-pull layer was built against `mcp.hubspot.com` (HubSpot's remote MCP server) per the original spec's own design decision — never against HubSpot's plain, standard REST API. This session's investigation (prompted by a direct question: "do we still need the Public App if we're using MCP endpoints?") found real, concrete reasons this is worth reversing: the Public App's own vaulted token is never actually read by any live pull today (confirmed in code); `mcp.hubspot.com` is a fully independent OAuth resource server with its own consent grant, so it isn't "extra security" layered on the Public App, it's a second, separate credential doing the same job a REST-scoped Public App token already could; and REST has real, better equivalents for what MCP gives us today — an authoritative `hubspotDefined` custom-property flag REST provides that MCP doesn't, and roughly double the real object types (~30 vs. the 16 this project currently reaches) that HubSpot's own MCP tool surface confirms are available on our real test portals but were never wired up. Retiring the MCP Auth App removes a whole second OAuth credential, a whole second install step, and a class of MCP-specific complexity (dynamic tool discovery, read-verb allowlisting) that exists only because MCP's tool surface isn't fixed and documented the way REST's is.

## What Changes

- **BREAKING**: `gateway/auth/mcp_auth.py`, the `/install/mcp-auth` and `/callback/mcp-auth` routes, and the `mcp_tokens` table are removed entirely. The MCP Auth App is no longer part of this project's architecture. **This is a deliberate reversal of a foundational decision in the original spec** (`HubSpot_MCP_Server_Spec_v1.2.md` Section 1.3: "Per-user OAuth with PKCE to HubSpot's remote MCP"), not an oversight — see `design.md` for the full reasoning and what's preserved from the original rationale.
- `gateway/sync/hubspot_client.py`'s internals are rebuilt to call HubSpot's plain REST API (`api.hubapi.com`) using the Public App's own vaulted token (already in the existing `tokens` table — no new vault, no new table) instead of `mcp.hubspot.com`. Public method signatures (`pull_crm_objects`, `discover_object_properties`, `pull_object`, `pull_campaign_data`) are preserved so downstream callers change minimally.
- MCP-specific dynamic-tool-discovery machinery (`list_read_only_tools`, `_is_read_safe`, `_has_write_verb`, `IN_SCOPE_OBJECT_KEYWORDS`, `PER_ITEM_TOOLS`, `PROPERTY_DISCOVERY_TOOLS`) is removed, replaced by a fixed, explicitly-documented REST endpoint allowlist — REST's endpoint set is fixed and known ahead of time, so runtime tool discovery/classification is no longer needed.
- Custom-field access moves to REST's `/crm/v3/properties/{objectType}` endpoint, which returns an authoritative `hubspotDefined` boolean per property — replacing this project's own `is_custom_property_name()` heuristic (built specifically because MCP's `search_properties` didn't expose this) with a real, HubSpot-confirmed signal.
- Onboarding a new client drops from two install steps to one — only the Public App install remains.
- Every test file that currently fakes an MCP `Client`/transport is updated to fake HTTP responses instead.
- All documentation describing the MCP Auth App as part of the architecture is updated: `CLAUDE.md`, `README.md`, `context/DATABASE.md`, `context/ONBOARDING_RUNBOOK.md`, `context/SETUP.md`, `.env.example`, `docker-compose.yml`.
- A Postman collection documenting this service's own exposed HTTP endpoints (not HubSpot's) is produced once the post-migration route set (minus `/install/mcp-auth`/`/callback/mcp-auth`) is stable.
- Unchanged: HubSpot access stays read-only, absolute. No write scopes, no write code paths. Airtable remains the only read-write integration.

## Capabilities

### New Capabilities
- `hubspot-rest-client`: the rebuilt data-pull layer itself — calling HubSpot's REST API with the Public App's token, covering the core CRM object set, custom-property discovery, and whatever of the current marketing/analytics/campaign read paths have real REST equivalents.

### Modified Capabilities
- `vertical-pull-agent`: the agent's tool surface is still restricted to already-allowlisted pull methods, but "allowlisted" now means a fixed REST endpoint set, not MCP's dynamically-discovered tool list. Isolation requirements carry forward unchanged in spirit.
- `hubspot-custom-field-access`: custom-property discovery moves from MCP's `search_properties` (no authoritative custom/standard flag, required a heuristic) to REST's `/crm/v3/properties/{objectType}` (a real `hubspotDefined` flag) — the heuristic (`is_custom_property_name`) is retired where the authoritative flag is available.
- `hubspot-query-tool-surface`: the live session's category-scoped tools are unaffected in shape, but the `properties` parameter's documented behavior changes — MCP's explicit-column selection was confirmed live to be additive (HubSpot's default set plus whatever's requested); REST's `properties` query parameter is a true explicit selection. This needs re-confirming live, not assumed to carry over.

## Impact

- `gateway/sync/hubspot_client.py` (~830 lines): near-total internal rebuild, same public interface.
- `gateway/auth/mcp_auth.py`, `/install/mcp-auth`, `/callback/mcp-auth`, `mcp_tokens` table: removed. `mcp_tokens` removal is a real data migration — real vaulted tokens for two real installed portals (`148997330`, `149094230`) currently live in that table; see `design.md`'s Migration Plan, not a blind `DROP TABLE`.
- `gateway/frameworks/profiling.py`, `gateway/frameworks/pull_agent.py`, `gateway/session/live_session.py`, `gateway/sync/airtable_staging.py`: expected to need minimal changes, since all depend on `HubSpotDataPullClient` only through its public method interface, not on MCP specifics.
- Every test file with an MCP-shaped fake transport (`test_hubspot_client.py`, `test_pull_agent.py`, `test_profiling.py`, `test_live_session.py`, `test_airtable_staging.py`).
- `gateway/schema.sql`, `.env.example`, `docker-compose.yml`: `mcp_tokens` table and `HUBSPOT_MCP_*` variables removed.
- Documentation: `CLAUDE.md`, `README.md`, `context/DATABASE.md`, `context/ONBOARDING_RUNBOOK.md`, `context/SETUP.md`.
- New deliverable: a Postman collection for this service's own HTTP endpoints.
- No change to Airtable staging's own logic, Sybill ingestion, the live session's Google OAuth Proxy, or the vertical/client agent separation's own two-tier persistence model (`vertical_agent_templates`/`client_agent_instances`) — those stay exactly as built, just now backed by REST-sourced data instead of MCP-sourced data.
