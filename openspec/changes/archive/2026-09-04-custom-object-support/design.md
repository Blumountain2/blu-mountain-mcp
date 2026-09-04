## Context

`HubSpotDataPullClient` (`gateway/sync/hubspot_client.py`) reads every standard HubSpot object type through a fixed, hand-enumerated mapping (`CRM_OBJECT_REST_SLUGS`) from an ALL_CAPS constant (`CONTACT`, `DEAL`, ...) to a REST slug (`contacts`, `deals`, ...), reviewed once at development time. This works because HubSpot's standard object set is fixed and known ahead of time — that was the whole premise of the REST pivot (`openspec/changes/hubspot-rest-api-pivot`).

Custom objects break that premise: they're defined per-portal, at runtime, by whoever configured that client's HubSpot instance. There is no way to know a custom object's identifier ahead of time — it must be discovered from the portal itself before it can be read. This is the actual reason custom objects were explicitly left out of the REST pivot (task 11.1) rather than folded in — it's a structurally different access pattern, not just one more entry in a lookup table.

This session's own review of Blu Mountain's six vertical framework documents confirmed this isn't a hypothetical gap: Marketplace needs Listing/Transaction/Match custom objects, Services/Project needs a custom "Project" object, and a real custom object ("Transaction") now exists on the Enterprise-tier test portal (`149094230`) specifically to verify this against.

## Goals / Non-Goals

**Goals:**
- Discover every custom object schema defined on a tenant's portal, at runtime, per call — never assumed or cached across tenants.
- Read one custom object's records and properties, given its discovered `objectTypeId`, using the exact same paginated-GET, read-only shape every standard object already uses.
- Degrade gracefully (not crash) on a portal without Custom Objects at all (baseline tier) or without the granted scope.
- Confirm live against the real "Transaction" custom object on `149094230` before considering this done — not just against test doubles.

**Non-Goals:**
- Wiring this into `frameworks/pull_agent.py`'s tool-use loop, `session/live_session.py`'s category tools, or `frameworks/profiling.py`'s field profiling. Each is a real, separate integration decision (does the client agent's system prompt need to explain custom objects to the model? does a live-session staff member need a fifth query tool? does profiling's guidance model extend to objects with no vertical-framework precedent?) — bundling them in here would mean guessing at three separate designs instead of deciding each deliberately.
- Any object-instance write path. Never in scope, anywhere in this project.
- Associations (`GET /crm/v4/objects/{type}/{id}/associations/{toType}`) — confirmed live to work the same way structurally, but nothing in this change's own scope (schema + record + property discovery) needs it yet. Left as a documented future extension, not built speculatively.
- A generic "any object type, standard or custom, through one unified method" refactor of `pull_crm_objects`. Standard objects keep their existing fixed-slug path unchanged; custom objects get their own parallel methods. Unifying them is a bigger refactor with its own risk, not needed to close this gap.

## Decisions

**Schema discovery is its own endpoint family, not a variant of the existing properties/objects calls.** `GET /crm-object-schemas/v3/schemas` lives under a different path prefix (`crm-object-schemas/v3`, not `crm/v3`) than every other endpoint this project calls — confirmed live via HubSpot's own docs, not assumed. `discover_custom_object_schemas()` is a new method with its own explicit URL, not a parameterization of `_paginate`'s existing `crm/v3/...` callers.

**`objectTypeId` is always caller-supplied, never a module-level constant.** Unlike `CRM_OBJECT_REST_SLUGS`, there is no fixed dict to look up a custom object's identifier in — a caller must call `discover_custom_object_schemas()` first (or already know the ID from a prior call) and pass the resulting `objectTypeId` (e.g. `"2-3465404"`) into `pull_custom_object()`/property discovery directly. This is a genuine, deliberate API shape difference from the standard-object methods, not an oversight — documented here so a future reader doesn't expect `CRM_OBJECT_TYPES`-style symmetry.

**Defense in depth on the `objectTypeId` string before it's interpolated into a URL**, mirroring `_is_safe_property_name`'s existing posture for property names: even though this is only ever a GET request, and even though in practice it comes from HubSpot's own schema-discovery response (never raw external input), the project's own established convention is not to trust "it's internal, so it's fine" — a plain identifier-shaped check (digits, hyphen) before use costs nothing and matches how every other caller-supplied identifier in this codebase is treated.

**Both new scopes are optional, matching `CAMPAIGN`/`QUOTE`'s established pattern, not a new mechanism.** `crm.schemas.custom.read` and `crm.objects.custom.read` go into `HUBSPOT_OPTIONAL_SCOPES`/the app manifest's `optionalScopes`, deployed via `hs project upload` the same way every prior optional-scope addition was. Confirmed live this session that Custom Objects is unavailable at the baseline tier at all (the create-object permission checkbox itself was greyed out for `148997330`) — requesting these as required would repeat the exact failure mode already hit and fixed for `marketing.campaigns.read`.

**Every method here returns `[]`/`{"error": "pull_failed"}` on failure, never raises to a `debug_api.py` caller** — same posture as every existing generic capability and non-standard object adapter (`CAMPAIGN`, `OBJECT_LIST`, etc.), logged via the same `hubspot_pull.tool_failed` event name so operators have one place to look regardless of which read path failed.

**`debug_api.py` gets two new endpoints, not folded into the existing `/crm/{object_type}` route.** A custom object's `objectTypeId` isn't a friendly alias the way `CRM_OBJECT_ALIASES` resolves `"contacts"` → `CONTACT` — forcing it through the same route would either break the existing alias-resolution contract or require special-casing inside it. Separate routes (`/custom-objects`, `/custom-objects/{object_type_id}`) keep both paths simple and matches this session's own precedent of adding focused new debug endpoints per capability.

## Risks / Trade-offs

- **[Risk] A custom object's `objectTypeId` is opaque and unmemorable** (`2-3465404`, not a friendly name) → **Mitigation**: `discover_custom_object_schemas()`'s response includes the schema's `name`/`labels` alongside its `objectTypeId`, so a caller (human via Postman, or code later) can resolve a friendly name to the ID in one prior call, the same two-step flow `debug_api.py`'s own "list tenants → pick hub_id" pattern already established this session.
- **[Risk] Confirming this live depends on one specific custom object existing on one specific portal** (`149094230`'s "Transaction") → **Mitigation**: also confirm the graceful-degradation path on `148997330` (no Custom Objects access at all) — both outcomes need to be real, not just the happy path.
- **[Trade-off] Not wiring into pull_agent.py/live_session.py/profiling.py leaves this capability reachable only via `debug_api.py` and direct code use for now** → accepted deliberately (see Non-Goals) — each of those integrations is a real design decision on its own, and this change's job is to prove the underlying capability works against a real custom object first.

## Migration Plan

No data migration — this is a pure capability addition, no schema/table changes. Rollout is the same scope-then-deploy-then-reinstall sequence already used for every prior optional scope in this project:
1. Add the two new methods + `debug_api.py` endpoints (code only, no live effect until scopes are granted).
2. Add `crm.schemas.custom.read`/`crm.objects.custom.read` to `HUBSPOT_OPTIONAL_SCOPES` and the app manifest's `optionalScopes`; deploy via `hs project upload`.
3. Reinstall both test portals (`/install`) to pick up the new grant.
4. Confirm live: `149094230` should actually see the real "Transaction" schema and be able to pull its (likely empty, since it's a fresh fixture) records; `148997330` should degrade gracefully, not crash, given it has no Custom Objects access at all.

## Open Questions

- Should `discover_custom_object_schemas()`'s result be cached anywhere (e.g. alongside `tenant_onboarding_profiles`), or always re-fetched live? Leaning toward always-live for this first change — caching schema discovery is exactly the kind of premature persistence this project's own `analysis-model-templates` design.md already warned against for framework content, and a portal's custom objects can change at any time.
- If/when this does get wired into `pull_agent.py`, does the client agent need a whole new tool (`list_custom_object_types`/`pull_custom_object_type`), or should `list_object_types`/`pull_object_type` be extended to also cover custom ones transparently? Deliberately not decided here — that's this change's own first Non-Goal.
