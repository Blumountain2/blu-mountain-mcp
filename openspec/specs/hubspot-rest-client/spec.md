# hubspot-rest-client Specification

## Purpose
Reading a tenant's HubSpot data directly via HubSpot's plain REST API (`api.hubapi.com`), using the Public App's own vaulted OAuth token — a hand-enumerated, reviewed allowlist of endpoints, with every existing public method signature preserved so nothing calling this client had to change.
## Requirements
### Requirement: All HubSpot data access uses the Public App's token against HubSpot's REST API
`HubSpotDataPullClient` SHALL authenticate every HubSpot request using the Public App's vaulted access token (`auth.vault`), sent as a Bearer token to `api.hubapi.com`. It SHALL NOT use `mcp.hubspot.com`, the MCP Auth App's token, or any `fastmcp`/MCP client/transport.

#### Scenario: A pull uses the Public App's token, never a second credential
- **WHEN** any `HubSpotDataPullClient` method makes a real HubSpot request
- **THEN** the only credential involved is the Public App's own vaulted token for that tenant

### Requirement: Public method signatures are preserved across the rebuild
`pull_crm_objects`, `discover_object_properties`, `pull_object`, and `pull_campaign_data` SHALL keep the same parameter and return shapes callers already depend on, so `frameworks/profiling.py`, `frameworks/pull_agent.py`, `session/live_session.py`, and `sync/airtable_staging.py` require no changes to their own logic.

#### Scenario: A downstream caller's existing test passes unmodified
- **WHEN** `HubSpotDataPullClient`'s internals are rebuilt against REST
- **THEN** existing tests in `test_pull_agent.py`, `test_profiling.py`, `test_live_session.py`, and `test_airtable_staging.py` that only exercise `HubSpotDataPullClient`'s public methods continue to pass without modification to their own assertions

### Requirement: Custom property discovery uses REST's authoritative standard/custom flag
`discover_object_properties()` SHALL use `GET /crm/v3/properties/{objectType}` and SHALL surface each property's real `hubspotDefined` value, rather than the heuristic `is_custom_property_name()` used under the prior MCP-based mechanism.

#### Scenario: A property's custom/standard status is authoritative, not guessed
- **WHEN** a tenant's properties are discovered for any object type REST's properties endpoint covers
- **THEN** each property's custom/standard classification comes from HubSpot's own `hubspotDefined` field, not a hand-curated heuristic

### Requirement: Every REST endpoint this project calls is a hand-enumerated, reviewed allowlist
`HubSpotDataPullClient` SHALL only ever call a fixed, explicitly-coded set of REST endpoints known and reviewed ahead of time. It SHALL NOT dynamically discover or construct endpoint paths from external input, and SHALL NOT perform any HTTP method other than GET against HubSpot (or a narrowly-scoped read-only POST, e.g. a search endpoint, only where explicitly reviewed as read-only).

#### Scenario: No caller-influenced endpoint construction reaches HubSpot
- **WHEN** any `HubSpotDataPullClient` method is called
- **THEN** the REST endpoint path is always one of this project's own hand-coded constants, never assembled from caller-supplied strings beyond a validated object-type name

### Requirement: A 429 rate-limit response degrades gracefully, not as a crash
If HubSpot's REST API returns `429`, the affected pull SHALL be logged and recorded as a failed pull for that object type/tool, the same way any other pull failure degrades today, rather than raising an unhandled exception that aborts the whole run.

#### Scenario: A rate-limited call doesn't crash the rest of a multi-object pull
- **WHEN** one object type's REST call returns `429` during a `pull_crm_objects` run covering multiple object types
- **THEN** that one object type is recorded as failed and every other object type in the same run still completes normally

### Requirement: No real capability is silently dropped in the migration
Every generic HubSpot read capability this project used via MCP (owners, organization details, content analytics, marketing email analytics, campaign attribution) SHALL either have a confirmed-live REST equivalent before its MCP path is removed, or be explicitly documented as a knowingly-dropped capability.

#### Scenario: A capability with no confirmed REST equivalent is not silently removed
- **WHEN** implementation reaches a generic tool whose REST equivalent has not been confirmed live
- **THEN** that capability's MCP path stays in place until a REST equivalent is confirmed, or its removal is explicitly documented as a deliberate trade-off

