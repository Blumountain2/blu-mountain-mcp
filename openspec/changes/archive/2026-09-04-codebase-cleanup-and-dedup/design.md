## Context

Two earlier informal `/code-review` passes this project ran (not formal OpenSpec changes) surfaced real, verified duplication findings that were deliberately left unfixed at the time — the applied scope on both passes was "confirmed bugs only," with simplification/reuse findings explicitly deferred pending the user's own priority call. Separately, the `client-vertical-agent-classes` migration deleted `gateway/frameworks/client_agent.py`/`vertical_templates.py` and dropped their tables, which broke two root scripts that imported the deleted module and left `context/DATABASE.md` describing tables that no longer exist.

Every item below was re-checked directly against the current code before being included here — several earlier findings turned out to already be resolved (e.g. `_NON_STANDARD_OBJECT_TYPES` being unconsulted by dispatch was fixed in an earlier round; the "duplicated latest-version query across 3 modules" finding is now moot since 2 of those 3 modules were deleted entirely by the agent-class migration) and are correctly *not* included here.

## Goals / Non-Goals

**Goals:**
- Remove genuinely dead/broken files.
- Correct documentation describing already-deleted database tables.
- Collapse each re-verified duplication into one shared implementation, with zero intended behavior change.

**Non-Goals:**
- `gateway/frameworks/agents/**` — stated directly by the user as out of scope. No file in that package is read, edited, or removed by this change, including `base.py`'s own internal patterns (e.g. its per-tool dispatch shape), even where they resemble something being deduplicated elsewhere.
- `gateway/frameworks/pull_agent.py` — the thin wrapper this change's boundary also covers by extension, since touching it means touching agent wiring.
- Any change to external behavior, API responses, or test expectations — every item here is refactor-only; the existing test suite is the proof, not a target to update.

## Decisions

**`hubspot_client.py`'s repeated client/headers-resolution pattern becomes a shared plain method, applied to 4 of the 6 original candidates — not one combined `@asynccontextmanager` applied to all 6, as originally planned.** Six methods (`pull_crm_objects`, `_fetch_property_definitions`, `discover_custom_object_schemas`, `pull_custom_object`, `pull_campaign_data`, `pull_object`) each hand-roll `owns_client = client is None; if owns_client: client, headers = await self._client_for_hub() ...` followed by a matching `finally: if owns_client: await client.aclose()`.

**Found during implementation, not anticipated when this was planned**: `pull_crm_objects`/`pull_campaign_data` have an *asymmetric* guard today — only the `owns_client` branch is wrapped in try/except; the `elif headers is None` branch is not. A single `@asynccontextmanager` wrapping resolve+body in one try/except (the original plan) would have newly caught a failure that currently propagates uncaught from those two specifically, a real behavior change this task's own success criterion explicitly forbids. The other 4 methods (`_fetch_property_definitions`, `discover_custom_object_schemas`, `pull_custom_object`, `pull_object`) don't have this asymmetry — their resolve-failure and body-failure already degrade to the identical return value and log tag, confirmed by reading each one directly — so merging their two try/except blocks into one is provably safe there.

Implemented as a plain `_resolve_client_and_headers(self, client, headers) -> (client, headers, owns_client)` (no exception handling inside it — it just raises naturally) applied to those 4, each still computing `owns_client = client is None` itself *before* the call (so the value survives a raised exception) and guarding its own `finally` with `if owns_client and client is not None` (needed because merging the two try blocks means `finally` can now run even when resolution itself failed, where the original two-try-block structure guaranteed it never would). `pull_crm_objects`/`pull_campaign_data` are left with their original inline resolve logic untouched, to avoid the risk entirely rather than engineer around it.

**Three one-line adapter methods become one path-keyed method.** `_pull_campaigns_as_records`/`_pull_landing_pages`/`_pull_blog_posts` each do nothing but `return await self._paginate(client, headers, "<fixed path>", {"limit": 100})`. Replaced with one `_pull_non_standard_object(self, path, client, headers)` and a small `_NON_STANDARD_OBJECT_PATHS = {"CAMPAIGN": "/marketing/v3/campaigns", "LANDING_PAGE": ..., "BLOG_POST": ...}` dict the dispatch branch reads from — collapsing 3 methods and 3 dispatch branches into 1 method and a data table, mirroring the same pattern `_GENERIC_CAPABILITIES` already uses successfully in this file.

**The tenant display-name fallback query becomes one shared SQL fragment constant, not a function.** `COALESCE(NULLIF(TRIM(portal_name), ''), NULLIF(TRIM(hub_domain), ''), hub_id)` is copy-pasted verbatim in `live_session.py`, `debug_api.py`, and `onboarding.py` — but a closer look during implementation showed these 3 call sites don't actually share a query *shape*: `onboarding.py` fetches one tenant by `hub_id`; the other two fetch a filtered list of every installed tenant, each with its own different `WHERE` clause (a staff-restrictions exclusion vs. none). A function trying to unify those would be more machinery than 3 genuinely-different queries justify — this is the exact "Postgres view rejected as too much machinery" reasoning already written below, just applying one level further to a function too. Instead, `TENANT_DISPLAY_NAME_SQL` (a plain string constant) lives in `auth/token_vault.py` alongside `get_installed_hub_ids()`, and each call site interpolates it into its own otherwise-unchanged query (`f"... {TENANT_DISPLAY_NAME_SQL} AS name ..."`) — safe as plain string formatting since it's a static fragment with no caller-supplied input.
- *Alternative considered — a Postgres view.* Rejected as more machinery than 3 call sites justify; a plain Python helper is simpler to review and test.

**Object-type alias resolution becomes one shared function in `hubspot_client.py`.** `debug_api.py`'s `_resolve_object_type` and `live_session.py`'s inline `all_matching_types = [t for t in CRM_OBJECT_TYPES if lowered in CRM_OBJECT_ALIASES.get(t, set())]` independently re-derive the same free-text-to-canonical-type matching. A new `resolve_object_type_aliases(text: str) -> list[str]` lives next to `CRM_OBJECT_ALIASES` (the data it reads) in `hubspot_client.py`, returning every matching canonical type (ambiguity-preserving, matching `live_session.py`'s existing behavior — the stricter subset `debug_api.py` needs is one `[0]`/length check at its own call site, not a second implementation).

**`debug_api.py` reuses `get_installed_hub_ids()` instead of re-deriving the same predicate.** `_require_installed_tenant` currently hand-writes `SELECT 1 FROM tenants WHERE hub_id = $1 AND install_status = 'installed'`. Changed to `if hub_id not in await get_installed_hub_ids(): raise HTTPException(404, ...)` — matching the exact predicate `get_installed_hub_ids()`'s own docstring already promises as the project's single source of truth for "what counts as an active tenant."

**`debug_api.py`'s duplicated `properties=` parsing becomes one helper.** `[p.strip() for p in properties.split(",") if p.strip()] if properties else None`, appearing at two call sites, becomes one `_parse_properties_param(properties: str | None) -> list[str] | None` both call.

**`debug_api.py`'s fake-instance construction is removed.** `list_object_types`'s `HubSpotDataPullClient("").list_read_only_tools()` instantiates a client with a placeholder empty `hub_id` purely to call a method that never reads `self.hub_id`. `list_read_only_tools` becomes a `@staticmethod` (or module-level function) on `HubSpotDataPullClient`, called without constructing an instance at all.

**`onboarding.py`'s per-field insert becomes one batched insert.** The `for object_type, field_profiles in profiled.items(): for fp in field_profiles: await conn.execute(INSERT ...)` loop becomes a single `executemany`-style batch (asyncpg's `conn.executemany()`, or one multi-row `INSERT ... SELECT * FROM unnest(...)` if `executemany` doesn't fit the existing transaction shape cleanly) — one round trip instead of up to hundreds for a tenant with many populated fields.

**`live_session.py`'s `_query_category` validates before resolving a connection.** The `all_matching_types`/`in_category_types` computation and the wrong-category early return currently happen *after* `http_client, headers = await client._client_for_hub()`. Reordered so the object-type/category check runs first — a wrong-category request (already a real, tested path) no longer pays for a vault lookup and connection construction it's about to discard.

**`context/DATABASE.md` is corrected, not just trimmed.** The `vertical_agent_templates`/`client_agent_instances` sections are removed; a short note in their place points to `context/VERTICAL_AGENT_CLASSES.md`/`CLIENT_AGENT_CLASSES.md` for how that configuration is actually stored now (as code, not as rows in this database) — consistent with how this file already handles other superseded mechanisms (e.g. the `mcp_tokens` removal note elsewhere in this project's docs).

## Risks / Trade-offs

- **[Risk] A refactor introduces a subtle behavior change despite best intentions.** → Mitigation: the full existing test suite (306 tests) must pass unchanged after every item; any item whose fix would require a test change is a signal to stop and re-scope that item, not to update the test to match.
- **[Trade-off] The shared `_resolve_client` context manager changes every one of the 6 call sites' code shape simultaneously.** → Accepted: reviewed as one mechanical, low-semantic-risk transformation (extract-method), not 6 independent judgment calls.

## Migration Plan

Pure refactor — no schema change, no data migration, no deploy-order concern. Land it, run the full suite, done.
