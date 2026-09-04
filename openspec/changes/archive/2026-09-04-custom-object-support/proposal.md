## Why

This session's own review of Blu Mountain's six real vertical framework documents found that several verticals depend on genuine custom HubSpot objects, not just custom properties on standard objects — Marketplace needs Listing/Transaction/Match custom objects, Services/Project needs a custom "Project" object. Confirmed live this session: a real custom object ("Transaction", created on test portal `149094230`, Enterprise tier) is completely invisible to the current pull tooling — `CRM_OBJECT_TYPES` is a fixed, hand-enumerated list of ~17 standard types with no runtime discovery mechanism, so a portal's own custom object schemas can never be reached no matter what `properties=` is passed. This was explicitly logged as out of scope by the REST pivot (`openspec/changes/hubspot-rest-api-pivot`, task 11.1) — this change is that follow-on, now that a real gap and a real test fixture both exist to build and verify against.

## What Changes

- `HubSpotDataPullClient` gains real custom-object discovery and read methods: list a portal's custom object schemas (`GET /crm-object-schemas/v3/schemas`), read one custom object's records (`GET /crm/v3/objects/{objectTypeId}`, same pagination shape as every standard object already pulled), and discover a custom object's own properties (reusing the existing `GET /crm/v3/properties/{objectType}` mechanism, which already works unmodified for a custom object's `objectTypeId`). Read-only throughout — no write path is ever added, matching this project's absolute non-negotiable.
- Two new OAuth scopes requested as **optional** (matching the existing `CAMPAIGN`/`QUOTE` pattern): `crm.schemas.custom.read` (schema discovery) and `crm.objects.custom.read` (record + property reads — confirmed to be one scope covering every custom object type on a portal generically, not fragmented per object). Custom Objects is an Enterprise-tier HubSpot feature; the baseline-tier test portal can't even create one, so these must degrade gracefully on a portal without that tier, the same way `CAMPAIGN` already does.
- `gateway/debug_api.py` gains endpoints to list a tenant's custom object schemas and pull one by `objectTypeId`, mirroring the existing `/debug/hubspot/*` pattern — the first real, testable surface for this capability.
- Live-confirmed against the real "Transaction" custom object already created on `149094230` — the actual proof this closes the gap, not just a test-double pass.

**Explicitly out of scope for this change** (deferred, not silently dropped — each is its own follow-on decision):
- Wiring custom objects into `frameworks/pull_agent.py`'s tool-use loop (the client agent doesn't yet know to ask about a tenant's custom objects).
- Wiring into `session/live_session.py`'s category-scoped query tools (staff can't yet query a custom object interactively through the live session).
- Wiring into `frameworks/profiling.py`'s tenant field profiling (custom object properties aren't yet profiled the way standard-object properties are).

## Capabilities

### New Capabilities
- `hubspot-custom-objects`: Generic, read-only discovery and pull of a portal's custom HubSpot object schemas and records, exposed through `HubSpotDataPullClient` and the debug HTTP API.

### Modified Capabilities
(none — this adds a new capability alongside the existing REST pull surface without changing any of its existing requirements)

## Impact

- `gateway/sync/hubspot_client.py`: new methods (`discover_custom_object_schemas`, `pull_custom_object`, custom-object property discovery reusing existing machinery).
- `gateway/debug_api.py`: new `/debug/hubspot/{hub_id}/custom-objects` and `/debug/hubspot/{hub_id}/custom-objects/{object_type_id}` endpoints.
- `hubspot-app/src/app/app-hsmeta.json`, `.env`/`.env.example`, `docker-compose.yml`: two new optional OAuth scopes.
- `gateway/tests/sync/test_hubspot_client.py`, `gateway/tests/test_debug_api.py`: new tests for the above.
- `postman/blu-mountain-mcp.postman_collection.json`: new requests for the debug endpoints.
- `CLAUDE.md`, `context/DATABASE.md` (if applicable): documentation of the new capability and its confirmed-live status.
- Real test portal `149094230` (Enterprise tier, its own real "Transaction" custom object already created) is the live-verification target; `148997330` (baseline tier) is used to confirm graceful degradation when Custom Objects isn't available at all.
