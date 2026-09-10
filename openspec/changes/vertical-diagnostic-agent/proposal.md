## Why

The vertical/client agent hierarchy (`client-vertical-agent-classes`) can already gather a tenant's real HubSpot data against its vertical's framework, but it is deliberately forbidden from interpreting that data — `vertical-pull-agent`'s own non-negotiable states "none of them may override this behavior." That leaves the actual point of the vertical frameworks (SaaS/Marketplace/etc. Weekly Diagnostic Prompt — a health/risk assessment and KPI narrative) undelivered: nothing in this project produces it today, and the previously-considered route (a separate, persisted analysis-job pipeline reading staged Airtable data) is explicitly deferred and unbuilt. After being shown the tradeoff directly (this exact gather-vs-interpret boundary has already flip-flopped twice in this project's history), the decision is to build the interpretation step directly into the existing agent hierarchy rather than start a new ingestion/analysis-job track. Separately, two smaller gaps surfaced while using the live session: a tenant's vertical assignment exists only as a Python class attribute with no way to see it without reading code, and the agent hierarchy's tool schemas/dispatch live inline in `base.py` rather than their own file, which will only get more cramped once a diagnostic tool is added.

## What Changes

- Add a diagnostic-producing second phase to the client agent run: after the existing gather phase completes (unchanged), a new phase reasons over the gathered records against that client's vertical framework text (`analysis_content`) and produces a real diagnostic narrative (health/risk assessment, KPI report) — the interpretation `vertical-pull-agent` currently forbids any agent class from producing.
- Expose this on demand through the live MCP session: a new tool a staff member can call in chat, tenant-scoped the same way the existing six tools are, returning the diagnostic narrative directly.
- Stage the same diagnostic output into Airtable, tagged by client, alongside the already-synced HubSpot data — every other artifact this project produces from a tenant's data already lands there.
- Audit every diagnostic run the same way every other HubSpot-derived access is audited (staff identity, tenant, timestamp).
- Add each tenant's vertical to the live session's `list_my_tenants` response, sourced from the client agent registry, so it's visible without reading code.
- Split the agent hierarchy's tool schemas and tool-dispatch logic out of `base.py` into their own module, ahead of adding the new diagnostic tool, so tool definitions have one clear home as the tool surface grows.
- Bring `gateway-package-layout` up to date with the codebase as it actually stands today: `frameworks/` has been a real fifth production subpackage (alongside `auth/`, `sync/`, `webhooks/`, `session/`) since `analysis-model-templates`/`client-vertical-agent-classes`, and `debug_api.py` has lived at the gateway root since `implement-hubspot-mcp-server`, but neither was ever added to this spec. A full audit of the rest of `gateway/` (beyond `frameworks/agents/`) found no actual structural problem — every other file is already exactly where its own subsystem's convention says it should be — only that the spec itself hadn't kept up. No code moves for this part; only the spec catches up to reality.
- **BREAKING**: `vertical-pull-agent`'s current absolute prohibition on any agent class producing interpretation is narrowed — that guarantee now applies specifically to the gather phase (tool-calling loop, isolation, allowlisted pull methods), not to the client agent run as a whole, which may now include a distinct, explicitly separate diagnostic phase.

## Capabilities

### New Capabilities
- `vertical-diagnostic-reporting`: the diagnostic phase that reasons over one client's gathered HubSpot data against its vertical's stored framework to produce a real diagnostic narrative, the live-session tool that returns it on demand, and staging that same output to Airtable.
- `tenant-vertical-visibility`: surfacing a permitted tenant's vertical assignment through the live session's tenant-listing tool, sourced from the existing client agent registry rather than a new data store.

### Modified Capabilities
- `vertical-pull-agent`: the "gathers data; never interprets" non-negotiable is scoped specifically to the gather phase (the tool-calling loop over allowlisted pull methods) rather than the client agent run as a whole; a separate, explicit diagnostic phase may now consume that phase's output to produce interpretation, but the gather phase itself gains no new tool, no loosened isolation, and no ability to produce interpretation from inside its own loop.
- `gateway-package-layout`: adds requirements for `gateway/frameworks/agents/`'s internal file layout (tool-calling loop mechanics stay in `base.py`; tool schemas and dispatch move to their own `tools.py`), and separately catches the spec up to two things already true of the codebase but never documented: `frameworks/` as the fifth production subpackage, and `debug_api.py` as a root-level infrastructure file alongside `main.py`/`config.py`/`db.py`.

## Impact

- `gateway/frameworks/agents/base.py`: gather phase stays as-is; gains a call-out to a new diagnostic phase after gathering completes.
- `gateway/frameworks/agents/tools.py` (new): tool schemas (`_TOOLS`) and dispatch (`_bind_tool_executor`) moved out of `base.py`.
- `gateway/frameworks/agents/diagnostics.py` (new, name TBD in design.md): the diagnostic phase itself.
- `gateway/session/live_session.py`: new tool for on-demand diagnostic reports; `list_my_tenants` gains a `vertical` field.
- `gateway/sync/airtable_staging.py`: new staging path for diagnostic output.
- `gateway/frameworks/agents/registry.py`: read (not modified) to resolve a hub_id's vertical for both the tenant-listing tool and the diagnostic phase.
- `openspec/specs/vertical-pull-agent/spec.md`, `openspec/specs/gateway-package-layout/spec.md`: requirement-level changes as described above.
