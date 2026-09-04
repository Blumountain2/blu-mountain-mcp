## 1. Base agent class

- [x] 1.1 Create `gateway/frameworks/agents/base.py`: `BaseAgent` abstract class. Move the tool-calling loop (the `while True`/tool-dispatch/stop-condition logic currently in `run_client_agent`), `MAX_TOOL_CALLS` handling, hub_id-scoped `HubSpotDataPullClient` construction, and audit logging (`pull_agent_run_completed`/`pull_agent_run_failed`, using `record_audit_best_effort`) out of `pull_agent.py` and into this class unchanged in behavior.
- [x] 1.2 Required subclass attributes: `VERTICAL: str`, `SYSTEM_PROMPT_ADDITIONS: str`. Optional: `MAX_TOOL_CALLS: int` override.
- [x] 1.3 `list_object_types`/`pull_object_type` tools (existing behavior, moved as-is) plus new `list_custom_objects`/`pull_custom_object` tools, wired to `discover_custom_object_schemas()`/`pull_custom_object()`/`discover_custom_object_properties()` — available on `BaseAgent` for every vertical/client uniformly.
- [x] 1.4 `CONFIRMED_FIELDS: dict[str, list[str]]` class attribute (default `{}`) on the client tier only. Executor checks `self.CONFIRMED_FIELDS.get(object_type)` before falling back to full discovery, matching the fallback semantics already designed for the (now-abandoned) DB-backed version: non-empty list narrows, empty/missing falls back to discovery.
- [x] 1.5 Test: `BaseAgent` alone (a minimal test subclass with no real vertical/client content) proves the loop mechanics work independent of any real vertical or client. Also added: confirmed-fields narrowing/fallback, custom-object tool tests, and a bare-vertical-class construction refusal — beyond the original task's minimum, since these are the same class's real behavior and needed coverage regardless.

## 2. Vertical classes

- [x] 2.1 Create `gateway/frameworks/agents/verticals/{saas,plg,marketplace,ecommerce,services_project,transactional}.py`, one class each, `VERTICAL` set, `SYSTEM_PROMPT_ADDITIONS` starting empty (matching today's real, unfilled `vertical_agent_templates` content — do not invent content that was never actually authored).
- [x] 2.2 Confirm each vertical class still reads its raw framework text from `analysis_content` (`frameworks.store.get_latest`) exactly as `run_client_agent` does today — this table is not moving into code. Verified via `tests/frameworks/agents/test_verticals.py`, parametrized across all 6 classes, plus a coverage test that every `KNOWN_VERTICALS` entry has a matching class.

## 3. Registry

- [x] 3.1 Create `gateway/frameworks/agents/registry.py`: `@register_client_agent(hub_id)` decorator populating a module-level `dict[str, type[BaseAgent]]`; a lookup function raising a clear `ValueError` naming the hub_id when unregistered.
- [x] 3.2 `gateway/frameworks/agents/clients/__init__.py` imports every client module so each self-registers on import.
- [x] 3.3 Test: registering two classes under the same hub_id (a mistake) is caught explicitly, not silently overwritten. Also covered: unregistered hub_id raises clearly, and re-registering the identical class object (module re-import) is a no-op, not a false-positive duplicate error.

## 4. Client classes (real migration)

- [x] 4.1 `149094230`'s vertical assignment resolved by the user: `148997330` is `saas`, `149094230` is `marketplace` (the old instance row pointing `149094230` at the `saas` template was simply wrong). Corrected directly in the live database via `set_tenant_vertical`.
- [x] 4.2 Author `clients/blu_mountain_gumpper.py` (`HUB_ID = "148997330"`, subclasses `SaaSAgent`) with `CONFIRMED_FIELDS = {}`, plus a code comment listing today's real `needs_review` field names as candidates for a human to actually curate, not silently treated as confirmed.
- [x] 4.3 Author `clients/blu_mountain_test_account.py` (`HUB_ID = "149094230"`, subclasses `MarketplaceAgent`) the same way, with its own real `needs_review` candidates including `DEAL`/`CAMPAIGN`, which `148997330` doesn't have.
- [x] 4.4 Isolation test: two client classes of the same vertical never cross-read each other's `CONFIRMED_FIELDS` or HubSpot token. `tests/frameworks/agents/test_real_clients.py` covers both real clients (different verticals) plus construction-time hub_id binding; `test_base.py`'s existing concurrent-runs/mid-loop-isolation tests already cover two same-vertical dynamic test classes.

## 5. Wire `run_client_agent` to the new path

- [x] 5.1 Replace `run_client_agent`'s internals with a registry lookup + instantiate + `.run()`. Decided during implementation: dropped `vertical`/`allow_unqualified` entirely rather than keeping them as no-ops — checked every real call site first (`main.py`/`debug_api.py` never called it at all; `live_verification.py` only ever called `run_client_agent(hub_id)` with no extra args), so nothing depended on those parameters and keeping them would only have been confusing dead surface.
- [x] 5.2 Rewrote `gateway/tests/frameworks/test_pull_agent.py` down to just the thin wrapper's own behavior (delegates to the registered class, raises clearly for an unregistered hub_id). Every loop-mechanics/isolation/tool-dispatch/audit test moved to `tests/frameworks/agents/test_base.py` (using a dynamically-built test agent class instead of DB fixtures), since that's where the logic itself now lives — not duplicated in both places.

## 6. Remove the superseded DB-backed system

- [x] 6.1 Delete `gateway/frameworks/vertical_templates.py`, `gateway/frameworks/client_agent.py`, and their test files.
- [x] 6.2 Drop `vertical_agent_templates`/`client_agent_instances` from `schema.sql` (idempotent `DROP TABLE IF EXISTS`, matching the existing `mcp_tokens` precedent) — only after tasks 4-5 confirm the new path fully replaces them.
- [x] 6.3 Remove both from `gateway/frameworks/__init__.py`'s exports.
- [x] 6.4 Grepped the whole repo. Found and fixed two real dangling references beyond the export list itself: `gateway/tests/conftest.py`'s `_TABLES` truncation list (would have errored every test run once the tables were dropped) and `gateway/scripts/live_verification.py` (imported `resolve_client_agent_instance`/`list_latest_templates` directly and drove steps 1/4 through the old API — rewritten to use the registry, and extended with a new step 6 exercising the real custom-object tools through the agent's own dispatch for the first time, per task 7.2). Two docstring-only mentions (`frameworks/vertical.py`, `frameworks/_versioning.py`) updated to stop referencing the deleted modules. Remaining hits are all either historical (`openspec/changes/*`, untouched) or explanatory comments describing what was removed and why.

## 7. Live verification

- [x] 7.1 Ran the real, migrated `148997330` client agent (`BluMountainGumpperAgent`) against real HubSpot + real Anthropic via `gateway/scripts/live_verification.py` step 4: gathered 21 real records across 13 object types. A real, pre-existing, already-documented gap surfaced again (not new): `CAMPAIGN` 403s on this portal (no Marketing Hub Pro+) and degraded gracefully to a logged failure, not a crash.
- [x] 7.2 Ran the real `149094230` client agent (`BluMountainTestAccountAgent`/`MarketplaceAgent`) the same way: gathered 21 real records across 12 object types/objectTypeIds — **the model itself organically chose to call `list_custom_objects`/`pull_custom_object` during its normal autonomous run**, pulling the real "Transaction" custom object (`2-252820399`) unprompted, not just in an isolated direct-dispatch test. Step 6 additionally confirmed the same reachability via direct executor dispatch (3 real records), independent of the model's own judgment.
- [x] 7.3 Full test suite passes (306/306, including all 39 new/rewritten agent tests); `python3 scripts/test_all.py` reports HEALTHY.

## 8. Operator documentation

- [x] 8.1 Wrote `context/VERTICAL_AGENT_CLASSES.md`: what a vertical class is, how to create a 7th one if ever needed, how to edit `SYSTEM_PROMPT_ADDITIONS`, and what "saved" means now (a commit + a deploy). States plainly there is no admin UI.
- [x] 8.2 Wrote `context/CLIENT_AGENT_CLASSES.md`: what a client class is, how `CONFIRMED_FIELDS` works for both standard and custom objects, that changes take effect on the very next run with no re-registration step, and how to create a new client's file end to end.
- [x] 8.3 Cross-linked both from `CLAUDE.md`'s vertical/client agent separation section.

## 9. Documentation sync

- [x] 9.1 Rewrote `CLAUDE.md`'s vertical/client agent separation section end to end: the class hierarchy, the dropped tables, the honest "nothing real was carried over" migration note, the resolved client-can't-override-behavior decision, and this recorded as the third round of the same recurring "per-client agent" decision this project's own design docs already track.
- [x] 9.2 Test counts already read 306 in both `CLAUDE.md` and `README.md` — this change's net test count (39 new/rewritten in `tests/frameworks/agents/` + `test_pull_agent.py`, minus everything removed with `test_client_agent.py`/`test_vertical_templates.py`) landed on the same total, confirmed via a real full run, no edit needed.
