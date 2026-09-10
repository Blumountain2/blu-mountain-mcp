## Context

`gateway/frameworks/agents/base.py::BaseAgent.run()` currently does one thing: run a bounded Claude tool-use loop that decides which allowlisted HubSpot pull methods to call, then return the raw gathered records (`object_type -> list[record]`). `vertical-pull-agent`'s spec makes this an absolute, structural guarantee — no vertical or client subclass has a code path to produce interpretation instead of raw data.

Separately, `gateway/frameworks/store.py` already holds each vertical's real, Blu Mountain-authored framework text (`analysis_content`, content_type `framework`), plus the vertical-agnostic operational skill and the `Weekly_Diagnostic_Prompt` runtime prompt (`analysis-template-schema`). Nothing today ever reads that prompt content and actually runs it — the diagnostic step it describes (health/risk assessment, KPI narrative) has no code path to be produced. The previously-sketched alternative (a persisted analysis-job pipeline consuming staged Airtable data) remains explicitly deferred (`tasks.md` Section 6 of `analysis-model-templates`) and, per this change's own proposal, is not the direction being taken — the interpretation step is built directly into the existing agent hierarchy instead.

Two smaller, unrelated gaps surfaced during live use of the MCP session and inform this design too: a tenant's vertical is only visible by reading `gateway/frameworks/agents/clients/*.py`, and `base.py` already mixes loop mechanics with tool schemas/dispatch in one file, which the new diagnostic tool would otherwise make worse.

## Goals / Non-Goals

**Goals:**
- Produce a real diagnostic narrative (not raw records) for one client, reasoning over that client's gathered HubSpot data against its vertical's stored framework text.
- Make that narrative available two ways: on demand through the live MCP session, and staged into Airtable alongside the client's synced HubSpot data.
- Keep the gather phase's existing isolation, allowlisting, and bounded-loop guarantees completely unchanged — the new phase consumes the gather phase's output, it does not modify how gathering works.
- Make a tenant's vertical visible through the live session without reading code.
- Give the agent hierarchy's tool schemas/dispatch a dedicated file before the tool surface grows further.

**Non-Goals:**
- No persisted, tenant-scoped "onboarding profile" or new analysis-job scheduler — this reuses the existing per-client agent run model (one run, one tenant, triggered on demand or via the existing scheduled sync cadence), not a new pipeline.
- No change to what the gather phase itself can do, which tools it exposes, or its isolation model — `vertical-pull-agent`'s guarantees continue to hold for that phase unchanged.
- No new LLM provider, model, or training — same shared Anthropic credential this project already uses everywhere else.
- This change does not attempt to programmatically execute the `Weekly_Diagnostic_Prompt`'s full multi-source scope (Slack, ClickUp, Harvest, Toggl, etc., per the prompt's own text) — same HubSpot-only scope `BaseAgent`'s current system prompt already declares; the diagnostic phase reasons only over HubSpot data this project can actually reach.

## Decisions

### Decision: A second, explicit phase on the same agent run — not a new "interpret from scratch" pipeline

After `BaseAgent.run()`'s existing gather loop completes (unchanged: bounded tool-calling loop, isolated to one `hub_id`, allowlisted pull methods only), a new `_diagnose()` step runs as a distinct, separately-named method: one more Claude call (or a short bounded loop, if the diagnosis step itself needs to re-read anything already gathered — see Open Questions) whose system prompt is the vertical's stored framework text plus the operational skill, and whose input is exactly the gathered records from the phase that just completed. Its output is free-text (or a light JSON envelope — see Open Questions), never fed back into another tool-calling loop, and never given tool access to HubSpot itself.

**Why this shape, not a rewrite of `BaseAgent.run()`'s single loop:** `vertical-pull-agent`'s existing guarantees (isolation, allowlist, bounded loop) are real, tested, and load-bearing for the gather step specifically. Keeping that step's code and contract untouched, and adding interpretation as a second, clearly-separated step that only ever *reads* the first step's output, means every existing isolation/allowlist test for the gather phase continues to hold unmodified — the new capability is additive, not a loosening of the tested code path itself. It also matches this project's own established pattern of "a new, real, separate thing" over "silently reinterpret an existing guarantee" (see `client-vertical-agent-classes`' own class-based rebuild vs. patching the old DB-driven model in place).

**Alternative considered:** Let the model interpret inline during the same tool-calling loop (e.g., a `submit_diagnosis` tool it can call once gathering feels sufficient). Rejected: this reintroduces exactly the ambiguity `vertical-pull-agent` was written to foreclose — a single loop where the same tool-execution path that can also decide to loosen its own behavior mid-run. A hard phase boundary (gather returns; diagnosis reads only what gather returned) is easier to reason about, test in isolation, and audit.

### Decision: Diagnosis runs per on-demand request, not folded into every scheduled sync cycle

The scheduled sync (`SYNC_INTERVAL_MINUTES`) keeps doing exactly what it does today — pull and stage raw data. The diagnostic phase runs only when explicitly triggered: from the new live-session MCP tool (a staff member asks for a report), or from a script/route a human runs deliberately. It is not wired into the scheduler in this change.

**Why:** The proposal's own requirement is "ask for a report and get one" — an on-demand read, not a new always-on job. Folding diagnosis into every sync cycle would mean an LLM call (cost, latency, another failure mode) on every tenant on every interval regardless of whether anyone wants a report that cycle. On-demand keeps the blast radius and cost model the same as everything else this project already gates behind an explicit ask.

**Alternative considered:** Run diagnosis automatically after every scheduled pull and always stage the result. Rejected for now as the default — nothing in the current ask requires a standing report to always exist; wiring the diagnostic phase into the scheduler later, if wanted, is a small additive change once there's a real cadence requirement (see Open Questions).

### Decision: One new live-session tool, tenant-scoped exactly like the existing six

`gateway/session/live_session.py` gains one new `@mcp.tool` (name TBD in tasks.md, e.g. `run_vertical_diagnostic`) that: requires a tenant already selected (same `_require_staff_identity()` / selected-tenant precondition every other data tool already enforces), instantiates that tenant's registered client agent class via the existing registry (`get_registered_agent_class(hub_id)`), runs its gather phase then its diagnosis phase, stages the result to Airtable (see below), audits the call, and returns the narrative directly as the tool's result.

**Why not a separate MCP server or route:** every other real HubSpot-derived access in this project already goes through this exact tenant-scoped, audited live-session tool pattern; a diagnostic report is just another HubSpot-derived access product, not a new access surface.

### Decision: Staging reuses `sync/airtable_staging.py`'s existing per-tenant, tagged-by-client pattern

A new normalization path (parallel to `normalize_record`/`normalize_sybill_transcript`) turns the diagnostic phase's output into one Airtable record per run: `hub_id`, vertical, generated-at timestamp, and the narrative text (plus any structured fields the JSON envelope decision below settles on), written via a small new function (e.g. `stage_diagnostic_report(hub_id, vertical, report)`) that follows the same `ensure_schema()`-provisioned-table convention `stage_tenant_pull` already uses. Staging happens as part of the same on-demand run that produces the report (not a separately triggered step) — a report a staff member asked for and a report visible in Airtable should never disagree about whether it happened.

**Alternative considered:** A wholly separate Postgres table for diagnostic history (closer to the previously-deferred "KPIs & Reporting" analysis-job design). Rejected for this change: Airtable is explicitly named in the ask, and this project already treats Airtable as the one read-write, analyst-facing destination for everything staged from HubSpot — a new Postgres table would be a second, redundant destination with no stated consumer.

### Decision: Vertical exposed on `list_my_tenants`, resolved from the existing registry, not a new lookup

`list_my_tenants` gains a `"vertical"` field per tenant, resolved via `registry.get_registered_agent_class(hub_id).VERTICAL` inside a try/except (or `registry.registered_hub_ids()` membership check first) — a permitted tenant with no registered client class yet (possible; not every installed tenant is guaranteed to have an authored agent class) gets `"vertical": None` rather than the whole tool call failing.

**Why not a new dedicated tool:** the proposal's own preferred option was adding the field to the existing tenant-listing response; a tenant's vertical is exactly the kind of fact someone asking "what are my tenants" wants alongside the name, and it avoids a second round-trip tool call for information already available at the same point in the code.

### Decision: The rest of `gateway/` is left untouched — only the spec catches up to it

Before finalizing this change, the full `gateway/` tree (not just `frameworks/agents/`) was audited against `gateway-package-layout` and against each subsystem's own internal convention. Findings:

- `frameworks/` (`store.py`, `ingest.py`, `_versioning.py`, `guidance.py`, `vertical.py`, `profiling.py`, `pull_agent.py`, plus the `agents/` subpackage) is a real, fully-formed fifth production subpackage — it has existed since `analysis-model-templates`/`client-vertical-agent-classes` — but `gateway-package-layout`'s "Gateway subpackage structure" requirement only ever named four (`auth/`, `sync/`, `webhooks/`, `session/`). This is a spec gap, not a code problem: every file already sits exactly where its own module's docstring says it should.
- `debug_api.py` lives at the gateway root, imported directly by `main.py`, spanning both the sync and auth subsystems (HubSpot pulls and the token vault) — the same "cross-cutting, not owned by one subpackage" rationale that already keeps `main.py`/`config.py`/`db.py` at the root. It was simply never added to that requirement's explicit file list.
- `scripts/` (`generate_confirmed_fields.py`, `live_verification.py`) is operator tooling, not imported by any production code path (confirmed: not referenced by `main.py` or any subpackage) — it is deliberately copied into a running container by hand per CLAUDE.md's own dev commands (`docker cp ... live_verification.py`), not part of the deployed package. It needs no spec coverage of its own, the same way `.env.example` or `postman/` don't.
- `gateway/tests/` already mirrors `frameworks/` (`tests/frameworks/`) and `frameworks/agents/` (`tests/frameworks/agents/`) in practice, ahead of the spec's own "Test structure mirrors subpackage layout" requirement, which likewise only named the original four.

**Decision:** fix the spec, not the code, for everything outside `frameworks/agents/` — `gateway-package-layout`'s spec delta (this change) updates the subpackage count to five, adds `debug_api.py` to the root-file list, and extends the test-mirror requirement to name `frameworks/` and its nested `agents/` test directory. No file in `gateway/` outside `frameworks/agents/` moves as part of this change.

**Why:** the proposal's own file-organization complaint was specifically about `frameworks/agents/`'s tool definitions; broadening this change into a repo-wide file-moving exercise would be scope creep unsupported by any actual finding — the audit confirmed nothing else is out of place.

### Decision: `tools.py` split — schemas and dispatch move out of `base.py`, the run loop stays

`gateway/frameworks/agents/tools.py` (new) holds `_TOOLS` (the tool schema list) and the tool-dispatch logic currently in `_bind_tool_executor`. `base.py` keeps `BaseAgent` itself (the loop, `_system_prompt`, `run()`) and imports from `tools.py`. The new diagnosis phase's own prompt-assembly logic (reading `analysis_content`, rendering the operational skill) lives alongside `_diagnose()` in `base.py` (or a small `diagnostics.py` if it grows past a few lines — see tasks.md) since it isn't a *tool* the model calls, it's the second phase's own prompt construction.

**Why now, not deferred again:** the user's own complaint was finding tool definitions in `base.py` when `tools.py` was expected; this change is about to add at least one more tool-shaped thing to the agent surface (the diagnosis step doesn't add a *model-callable* tool, but the live-session diagnostic tool is new surface area too), so this is the natural point to stop compounding the same file-organization gap rather than let it grow further first.

## Risks / Trade-offs

- **[Risk] A diagnostic narrative is a business judgment now embedded in this codebase's own liability surface (unlike raw HubSpot data, which merely mirrors what HubSpot already holds) →** Mitigation: the diagnosis phase's system prompt is exactly Blu Mountain's own authored framework/skill text, unmodified (per `analysis-template-schema`'s existing non-negotiable) — this project supplies the mechanism, not the judgment criteria; audit every run so any narrative is traceable to the exact framework version, gathered data, and staff member who requested it.
- **[Risk] Cost/latency: two LLM calls (or more) per on-demand report instead of one gather-only run →** Mitigation: on-demand only (not part of every sync cycle, per the decision above); the existing `MAX_TOOL_CALLS` bound already caps the gather phase, and the diagnosis phase is a single bounded call, not another open-ended loop.
- **[Risk] Narrowing `vertical-pull-agent`'s non-negotiable could be read as reopening a boundary that has already flip-flopped twice →** Mitigation: the spec delta keeps the gather phase's guarantee completely intact (isolation, allowlist, bounded loop, no interpretation *from inside that phase*); only the run-as-a-whole gains a distinct, separately-specified second phase — this change documents that distinction explicitly in the spec delta rather than deleting the requirement.
- **[Risk] A diagnostic report becomes stale relative to the client's live HubSpot data if staged once and not refreshed →** Mitigation: each report is timestamped at staging; refresh cadence (re-run on demand vs. a future scheduled cadence) is an Open Question below, not silently assumed.

## Migration Plan

1. Land the `tools.py` split first (no behavior change — pure move, existing tests must still pass unchanged).
2. Add the diagnosis phase and its Airtable staging path, behind the new live-session tool only (no scheduler wiring) — deployable and testable independent of any client actually calling it yet.
3. Add the `list_my_tenants` vertical field — independent, low-risk, can land in any order relative to 1-2.
4. Update `vertical-pull-agent`'s spec delta and confirm existing gather-phase tests (isolation, allowlist, bounded loop) still pass unmodified — no test should need to change to accommodate this narrowing, since the gather phase's code doesn't change.
5. Manually verify end-to-end against both real test portals (148997330 SaaS, 149094230 Marketplace) before considering this done: request a report live through MCP Inspector/Claude Code, confirm the narrative reads as a real interpretation (not raw records), and confirm the corresponding Airtable record appears.

No rollback complexity beyond normal revert: nothing here migrates existing data or changes any existing table's schema in a way earlier code depends on (the new Airtable table/fields and the `tools.py` split are additive).

## Open Questions

- ~~Should the diagnosis phase's output be plain free text, or a light structured envelope...~~ **Resolved during implementation:** a light structured envelope (`{"summary": str, "kpis": [{"name","value","note"}], "risk_flags": [str]}`), forced through a single non-HubSpot output-shaping tool (`submit_diagnostic_report`) rather than parsed from free text — see `gateway/frameworks/agents/diagnostics.py`.
- Does the diagnosis phase ever need its own tool access (e.g., to re-check one more object type it decides it needs), or is "reason only over what gather already produced" a hard rule for this phase too? This change assumes the latter (no tool access in the diagnosis phase) unless a real client's framework proves that insufficient.
- Should a diagnostic run ever be triggered automatically (e.g., a weekly cadence per client, matching "Weekly Diagnostic Prompt"'s own name), or does on-demand-only remain the model going forward? Left for a future change once real staff usage shows a pattern, consistent with how this project already treats new MCP prompts/tools ("real usage should drive what's added next, not a guess").
- Exact new tool name for the live session (`run_vertical_diagnostic` vs. `generate_diagnostic_report` vs. something else) — settled in `tasks.md`, not architecturally significant.
