## 1. File layout: split tools out of base.py (land first, no behavior change)

- [x] 1.1 Create `gateway/frameworks/agents/tools.py`; move `_TOOLS` and `_bind_tool_executor`'s body out of `base.py` into it, unchanged
- [x] 1.2 Update `base.py` to import from `tools.py`; `BaseAgent` keeps only the run loop, prompt assembly, and orchestration
- [x] 1.3 Run the full existing test suite (`docker compose run --rm --user 0 mcp-gateway sh -c "pip install --no-cache-dir -q -r requirements-dev.txt && pytest -q"`) and confirm no test needed to change to accommodate the move — 301 passed, unchanged
- [x] 1.4 Confirm `gateway/frameworks/agents/` now matches the layout in the `gateway-package-layout` spec delta (`base.py`, `tools.py`, `registry.py`, `verticals/`, `clients/`, each with `__init__.py`)
- [x] 1.5 No file moves needed elsewhere in `gateway/` (confirmed by this change's own audit — see design.md's "The rest of gateway/ is left untouched" decision); this task is documentation-only: confirm `openspec/specs/gateway-package-layout/spec.md` is updated (via this change's own spec delta) to name `frameworks/` as the fifth subpackage, add `debug_api.py` to the root-file list, and extend the test-mirror requirement to name `tests/frameworks/` and `tests/frameworks/agents/`

## 2. Tenant vertical visibility (independent, can land any time after/alongside Section 1)

- [x] 2.1 Add a helper (`registry.vertical_for_hub_id`) resolving a `hub_id` to its vertical, returning `None` when the hub_id isn't registered
- [x] 2.2 Update `list_my_tenants` in `gateway/session/live_session.py` to include `"vertical"` per tenant using that helper (wired into `_permitted_tenants`, so `select_tenant`'s own candidate matching is unaffected — it doesn't use the vertical field)
- [x] 2.3 Update `list_my_tenants`'s docstring to document the new field, including the `None`-for-unregistered-tenant case
- [x] 2.4 Add/update tests: `test_registry.py` (vertical_for_hub_id registered/unregistered), `test_live_session.py` (list_my_tenants includes real vertical for a registered tenant; None for an unregistered one; updated the existing real-transport round-trip assertion for the new field shape) — 305 passed
- [x] 2.5 Verified live (real Client<->FastMCP transport): `list_my_tenants` returns `{"hub_id": "148997330", ..., "vertical": "saas"}` and `{"hub_id": "149094230", ..., "vertical": "marketplace"}` — correct for both real portals

## 3. Diagnostic phase (depends on Section 1)

- [x] 3.1 Decided: a light structured envelope — `{"summary": str, "kpis": [{"name","value","note"}], "risk_flags": [str]}` — forced via a single non-HubSpot output-shaping tool (`submit_diagnostic_report`, `tool_choice` pinned to it) rather than parsed from free text. Gives Airtable real queryable fields (Section 4) while still rendering cleanly in chat (Section 5).
- [x] 3.2 Implemented as `gateway/frameworks/agents/diagnostics.py::produce_diagnostic_report()` (system prompt = runtime prompt with `{CLIENT_NAME}`/`{VERTICAL_FRAMEWORK_NAME}` substituted, plus the operational skill and vertical framework, via `frameworks/store.py::get_latest`) and `BaseAgent.diagnose()` (thin wrapper: calls it with this run's own gathered data, audits, returns the report)
- [x] 3.3 Confirmed: `diagnostics.py` has no `HubSpotDataPullClient` import, no tool schema reaching HubSpot, and its one tool (`submit_diagnostic_report`) only shapes output — never calls anything
- [x] 3.4 Confirmed: `run()`'s code and output shape are untouched; full suite (316 tests) passes with no gather-phase test modified
- [x] 3.5 Added `diagnostic_run_completed`/`diagnostic_run_failed` audit entries (hub_id, vertical) via `record_audit_best_effort`, matching `run()`'s existing convention; staff-identity-bearing audit is layered on top by the live-session tool in Section 5 (`_audit`), same as every other tenant-scoped tool
- [x] 3.6 Added `tests/frameworks/agents/test_diagnostics.py` (report shape, prompt substitution, no-HubSpot-tool-access, missing-content error, no-tool-call error) and `test_base.py` additions (diagnose() returns the narrative not raw records, only this run's own gathered data reaches it, audited success/failure) — 316 passed total

## 4. Airtable staging for diagnostic reports (depends on Section 3.1's output-shape decision)

- [x] 4.1 Extended `ensure_schema()` to provision `DiagnosticReports` (Client, Vertical, Summary, KPIs, Risk Flags, Generated At)
- [x] 4.2 Added `stage_diagnostic_report(hub_id, vertical, report)`, following `stage_tenant_pull`'s per-tenant, tagged-by-client convention; exported from `sync/__init__.py` alongside the other cross-subpackage sync exports
- [ ] 4.3 Wire staging into the same run that produces a report (not a separately triggered step) so a returned report and its Airtable record can never disagree about whether staging happened — done in Section 5 (the new live-session tool calls both)
- [ ] 4.4 Log/audit a staging failure distinctly from a successful stage, without misreporting success to the caller — done in Section 5
- [x] 4.5 Wrote tests covering: `ensure_schema` creates/skips `DiagnosticReports`; `normalize_diagnostic_report` tags by client/vertical; `stage_diagnostic_report` writes one row and isolates across tenants — 320 passed total

## 5. Live-session diagnostic tool (depends on Sections 3 and 4)

- [x] 5.1 Named it `run_vertical_diagnostic` (no parameters — operates on the session's already-selected tenant); added to `gateway/session/live_session.py`, gated by `_require_staff_identity()`/`_resolve_selected_tenant()` like the other tenant-scoped tools
- [x] 5.2 Wired: `get_registered_agent_class(hub_id)` -> `agent.run()` -> `agent.diagnose(gathered)` -> `stage_diagnostic_report(...)` -> `_audit(...)` -> returns `{**report, "staged": bool}`
- [x] 5.3 An unregistered tenant's `get_registered_agent_class` ValueError propagates as-is (already names the missing hub_id clearly); a staging failure sets `"staged": False` and audits `live_diagnostic_staging_failed` distinctly, without discarding or hiding the already-generated report
- [x] 5.4 Added `test_real_transport_run_vertical_diagnostic_round_trip` plus unit-level tests (report+staging returned, only this run's own gathered data reaches diagnose, staged:false on staging failure, clear error for an unregistered tenant) and updated `test_real_transport_lists_all_eight_tools_with_correct_schemas` for the 9th tool — 328 passed total
- [x] 5.5 Added `step7_run_vertical_diagnostic_real()` to `live_verification.py`; also fixed a real regression this surfaced: step6 still called the removed `BaseAgent._bind_tool_executor` method (Section 1's split moved it to `tools.bind_tool_executor`) — not caught by pytest since this script isn't part of the automated suite. Confirmed live: Steps 1-6 all PASS against real HubSpot/Anthropic/Postgres.
- [x] **Found and fixed via this live run, before Section 6**: `produce_diagnostic_report`'s `max_tokens=4096` truncated mid-tool-call against a real gathered dataset and a real client's full Weekly Diagnostic Prompt content, producing a `submit_diagnostic_report` call with required fields silently missing (empty `summary`, `kpis: None`, `risk_flags: None` reached the caller with no error). Fixed: `max_tokens` raised to 16384, a `stop_reason == "max_tokens"` check raises clearly instead of returning a truncated report, and a missing-required-field check raises clearly instead of silently passing through an incomplete dict (empty `[]`/`""` values are still legitimate, only outright key absence is treated as malformed) — see `diagnostics.py`. Separately, the real Airtable base didn't have `DiagnosticReports` (or, pre-existing and unrelated to this change, `Quotes`/`MarketingEmailAnalytics`) provisioned yet — fixed by running `ensure_schema()` against the real base, not a code change.

## 6. Spec finalization and full verification

- [x] 6.1 Full test suite: 328 passed, final run; no gather-phase (`vertical-pull-agent`) test needed any change across the whole implementation
- [x] 6.2 Verified live end-to-end via `gateway/scripts/live_verification.py` (real Client<->FastMCP transport, real HubSpot, real Anthropic, real Airtable) against both real test portals:
      - `148997330` (SaaS): real narrative report — correctly identified the portal as sandbox/demo data, applied the real SaaS framework's data-adequacy floors (ARR coverage, line items, meeting outcomes, ownership coverage), flagged 4 breached floors as the sole highest-priority finding per the operational skill's own "Required Context" rule, and staged successfully to Airtable.
      - `149094230` (Marketplace): real narrative report — 25 KPIs, 19 risk flags, applied the Marketplace framework, staged successfully to Airtable.
      - Both runs used `stop_reason`/missing-field checks added after the max_tokens fix; neither triggered them (no truncation on either real portal at 16384).
- [x] 6.3 CLAUDE.md updated: subpackage list now names `frameworks/` and `debug_api.py`, test count corrected to 328, and a new "Vertical diagnostic reporting" section documents the diagnostic phase, the `tools.py` split, the max_tokens regression found and fixed, the new `run_vertical_diagnostic` tool, and `list_my_tenants`'s `vertical` field — all only after both real portals were confirmed live above
- [ ] 6.4 Run `openspec-sync-specs` (or archive this change) once the user has reviewed the implementation
