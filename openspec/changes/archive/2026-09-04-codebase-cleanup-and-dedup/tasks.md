## 1. Remove dead/broken files

- [x] 1.1 Delete `shared_client_test.py` and `show_concurrent_isolation.py` (root) — confirmed genuinely broken, not just redundant: `show_concurrent_isolation.py` imports `frameworks.client_agent`, a module `client-vertical-agent-classes` deleted entirely.

## 2. Correct stale documentation

- [x] 2.1 Remove `context/DATABASE.md`'s `vertical_agent_templates`/`client_agent_instances` sections (they describe two dropped tables); replace with a short pointer to `context/VERTICAL_AGENT_CLASSES.md`/`CLIENT_AGENT_CLASSES.md` for how that configuration is actually stored now.
- [x] 2.2 Fix the same file's "Cross-cutting notes" section, which still names both dropped tables in its cascade/no-hard-delete summary.

## 3. `sync/hubspot_client.py` dedup

- [x] 3.1 Added `_resolve_client_and_headers(self, client, headers) -> (client, headers, owns_client)` instead of the originally-planned single combined `@asynccontextmanager`. **Deliberate design adjustment found during implementation**: `pull_crm_objects`/`pull_campaign_data` have an *asymmetric* guard today (only the owns-client branch is wrapped in try/except; the `elif headers is None` branch isn't) — a single context manager wrapping the whole resolve+body in one try/except would have newly caught a failure that currently propagates from those two specifically, a real behavior change. Applied the shared resolver to the 4 methods where resolve-failure and body-failure already degrade to the *identical* value and log tag (`_fetch_property_definitions`, `discover_custom_object_schemas`, `pull_custom_object`, `pull_object`) — merging their two try/except blocks into one is provably safe there. Left `pull_crm_objects`/`pull_campaign_data` untouched to avoid the risk. Verified via direct code inspection, not assumed.
- [x] 3.2 Replaced `_pull_campaigns_as_records`/`_pull_landing_pages`/`_pull_blog_posts` with one `_pull_non_standard_object(self, path, client, headers)` plus a `_NON_STANDARD_OBJECT_PATHS` dict the `_pull_one` dispatch branch reads from.
- [x] 3.3 Added `resolve_object_type_aliases(text) -> list[str]`. Confirmed via direct check (no alias string is ever shared by two different canonical types) that adding the exact-canonical-name check safely closes a tiny pre-existing gap in `live_session.py` too: `OBJECT_LIST`'s own lowered form isn't itself one of its aliases, so a caller literally passing "OBJECT_LIST" previously wouldn't have matched there (it already worked in `debug_api.py`, which had its own separate exact-name check) — now both share the same, more complete behavior.
- [x] 3.4 Made `list_read_only_tools` a `@staticmethod`; `debug_api.py` now calls `HubSpotDataPullClient.list_read_only_tools()` directly, no placeholder instance.
- [x] 3.5 Full suite passes unchanged (306/306).

## 4. Shared tenant-name helper

- [x] 4.1 **Adjusted during implementation**: added `TENANT_DISPLAY_NAME_SQL` as a plain string constant to `auth/token_vault.py` (exported via `auth/__init__.py`, alongside `get_installed_hub_ids()`), not a function — the 3 call sites turned out to fetch genuinely different query shapes (one tenant by `hub_id` vs. two different filtered multi-tenant lists), so a function trying to unify them would be more machinery than justified. See `design.md` for the full reasoning.
- [x] 4.2 Updated `session/live_session.py`, `gateway/debug_api.py`, and `frameworks/onboarding.py`'s `_effective_tenant_name` to interpolate the shared constant into their own otherwise-unchanged queries.
- [x] 4.3 Full suite passes unchanged (306/306); confirmed no circular import between `auth` and `frameworks`.

## 5. `debug_api.py` cleanup

- [x] 5.1 Replaced `_require_installed_tenant`'s hand-written query with `if hub_id not in await get_installed_hub_ids(): raise HTTPException(404, ...)`.
- [x] 5.2 Added `_parse_properties_param`. Caught a subtle edge case before finalizing: a naive helper returning `parsed or None` would return `None` for an all-blank input like `"?properties=,"`, where the original inline code returns `[]` — harmless downstream (`pull_custom_object` treats both identically via `properties or []`) but would have changed what value lands in the audit log's own recorded detail for that call. Fixed to match the original exactly.
- [x] 5.3 Full suite passes unchanged (306/306).

## 6. `onboarding.py` batched insert

- [x] 6.1 Replaced the per-field loop with one flattened `field_rows` list comprehension (skipping unpopulated fields, computing `status` the same way) plus a single `await conn.executemany(INSERT ..., field_rows)` inside the same transaction — no insert at all when `field_rows` is empty, matching the original's own no-op-on-zero-fields behavior.
- [x] 6.2 Full test suite passes unchanged.

## 7. `live_session.py` validate-before-connect

- [x] 7.1 Reordered `_query_category`: `category_types`/`all_matching_types`/`in_category_types` and the wrong-category early return now run before `http_client, headers = await client._client_for_hub()`; the early return no longer happens inside `async with http_client:` since there's no connection yet to close.
- [x] 7.2 Full test suite passes unchanged after this section — including the existing wrong-category-rejection test.

## 8. Final verification

- [x] 8.1 Full test suite passes (306/306, no new tests needed — this change is refactor-only and the existing suite is the correctness proof).
- [x] 8.2 `python3 scripts/test_all.py` passes — OVERALL: HEALTHY.
- [x] 8.3 `git diff --stat -- gateway/frameworks/agents/ gateway/frameworks/pull_agent.py` shows **zero** diff for `gateway/frameworks/agents/**` (empty output). `pull_agent.py` does show a diff against `HEAD`, but it predates this change entirely — it's the already-archived `client-vertical-agent-classes` migration's own rewrite, still uncommitted from before this cleanup change started; no file in this cleanup change's task list ever names or edits `pull_agent.py`, and no edit was made to it during this change's implementation.
