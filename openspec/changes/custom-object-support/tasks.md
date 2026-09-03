## 1. Client: schema discovery

- [x] 1.1 Added `discover_custom_object_schemas(client=None, headers=None)` to `HubSpotDataPullClient`: calls `GET https://api.hubapi.com/crm-object-schemas/v3/schemas`, returns a list of `{objectTypeId, name, labels}` per real schema, filtered through `_is_safe_object_type_id` defensively.
- [x] 1.2 Never raises to the caller: a 403 (no Custom Objects access), a token-fetch failure, or any other failure degrades to `[]`, logged via `log_pull_failure`.
- [x] 1.3 Isolation test (`test_discover_custom_object_schemas_only_uses_this_tenants_token`) proves schema discovery only ever uses the requesting tenant's own vaulted token.

## 2. Client: reading records and properties by objectTypeId

- [x] 2.1 Added `pull_custom_object(object_type_id, client=None, headers=None, properties=None)`: paginated `GET /crm/v3/objects/{object_type_id}`, reusing `_paginate`. `_is_safe_object_type_id` checked before any call is made.
- [x] 2.2 Added `discover_custom_object_properties(object_type_id, ...)`, reusing a new shared `_fetch_property_definitions` helper extracted from `discover_object_property_definitions` — same `GET /crm/v3/properties/{type}` mechanism, now parameterized by either a `CRM_OBJECT_REST_SLUGS` slug or a raw `objectTypeId`.
- [x] 2.3 Both degrade to `{"error": "pull_failed"}`/`[]` on failure, never raise — confirmed via tests, not just by inspection.
- [x] 2.4 Isolation tests for records (`test_pull_custom_object_only_uses_this_tenants_token`) and properties (reuses the same `_fetch_property_definitions` path already isolation-tested for standard objects).
- [x] 2.5 13 new tests in `tests/sync/test_hubspot_client.py`: real pagination, explicit `properties=`, unsafe-input rejection before any call, 403/failure degradation, real property discovery. Full suite: 54/54 passing.

## 3. OAuth scopes

- [x] 3.1 Added `crm.schemas.custom.read` and `crm.objects.custom.read` to `hubspot-app/src/app/app-hsmeta.json`'s `optionalScopes`; deployed via `hs project upload` (build #9).
- [x] 3.2 Added both to `HUBSPOT_OPTIONAL_SCOPES` in `.env` and `.env.example`, with a comment explaining why they're optional.

## 4. Debug HTTP API

- [x] 4.1 Added `GET /debug/hubspot/{hub_id}/custom-objects` to `gateway/debug_api.py`: lists the tenant's real custom object schemas. Same API-key gate and installed-tenant check as every other route in that module.
- [x] 4.2 Added `GET /debug/hubspot/{hub_id}/custom-objects/{object_type_id}` (optional `?properties=`): pulls that custom object's records. Records `debug_api_custom_object_schemas`/`debug_api_custom_object_pull` audit events, matching the existing `debug_api_*` naming pattern.
- [x] 4.3 6 new tests in `tests/test_debug_api.py`: unknown tenant, real schemas/records via the fake client, explicit `properties=`, isolation. Full suite: 295/295 passing.
- [x] 4.4 Added "List custom object schemas" (auto-fills `custom_object_type_id` from the first result, same pattern as "List installed tenants") and "Pull a custom object's records" to the Postman collection. Confirmed live via `newman`: 11/11 requests pass in the "Debug: HubSpot Data" folder.

## 5. Live verification — the actual point of this change

- [x] 5.1 Both test portals reinstalled after 3.1/3.2 (build #9) landed — confirmed via server-side audit log timestamps (12:58-12:59pm) well after the build deploy (10:10am), so this was a real, correctly-timed reinstall, not a race.
- [x] 5.2 **Unblocked 2026-09-03, root cause was portal-side, not HubSpot review**: earlier reinstalls kept showing `crm.schemas.custom.read`/`crm.objects.custom.read` ungranted, including two rounds this session that looked like a genuine HubSpot "sensitive scopes" Ecosystem Quality review gate. The real cause: HubSpot portals have a separate **Connected Apps admin data-permissions toggle**, per optional scope, that must be explicitly enabled by a portal admin before that scope is even selectable on the OAuth consent screen (shown as a locked checkbox with "This permission is disabled for this app by an admin" otherwise) — and the consent screen itself was serving a stale/cached permission set in a normal browser tab. Once the user (a) toggled the scopes on in Connected Apps admin settings and (b) reinstalled in a fresh incognito session, both scopes granted immediately on both portals — confirmed via token introspection. Live-verified against the real "Transaction" custom object on `149094230` (`objectTypeId 2-252820399`): `GET /debug/hubspot/149094230/custom-objects` discovers it, `GET /debug/hubspot/149094230/custom-objects/2-252820399` returns its 3 real records. The earlier "Ecosystem Quality review" theory documented in this file and CLAUDE.md was incorrect — see CLAUDE.md's corrected note.
- [x] 5.3 Confirmed live against both portals: `discover_custom_object_schemas()` returns `[]` gracefully on both (neither has the scope), rather than crashing — the degradation path itself is proven, independent of whether the scope is ever granted.
- [x] 5.4 Full automated test suite passes (295/295); `python3 scripts/test_all.py` passes.

## 6. Documentation

- [x] 6.1 Updated `CLAUDE.md`'s Data pull section: documents the new capability, its Non-Goals, and — beyond this change's original scope but discovered while confirming it — the full root-caused explanation for why `LINE_ITEM`/`USER`/custom-object scopes still aren't grantable (HubSpot's sensitive-scopes review process, installer-permission gating, a dead scope name, and the separately-discovered PRODUCT gap).
- [x] 6.2 Synced test counts (295) across `CLAUDE.md`/`README.md`.
