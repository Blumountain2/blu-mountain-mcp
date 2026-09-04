## Context

Today, `gateway/frameworks/pull_agent.py::run_client_agent(hub_id)` resolves a `client_agent_instances` row (producing one from `vertical_agent_templates` if absent) and assembles a system prompt from that data at call time — one shared function, parameterized by database rows. Leadership direction, given directly in this change's own scoping conversation, is that this must instead be real, separate, version-controlled code: one class per vertical, one class per client, sharing only the tool-calling loop mechanics that the Anthropic API itself forces to be identical for everyone.

This is a further, deliberate reversal beyond `separate-vertical-client-agents`, which itself already reversed `analysis-model-templates`' original "one shared agent config per vertical" non-negotiable — but only as far as persisted *data*, explicitly stating *"'AI agent per client' means a persisted prompt/context bundle... not per-client infrastructure."* This change goes further than that directive did. It is being made anyway, on direct instruction, with full visibility into that history — recorded here as the same kind of knowing, documented supersession this project has made twice before, not a silent contradiction.

Two real facts checked directly against the running dev database inform how much there is to actually migrate:
- Both existing `client_agent_instances` rows (`148997330`, `149094230`) have `injected_documentation` reading *"No fields have been confirmed relevant for this client yet"* — zero fields were ever actually confirmed relevant in the database version.
- All 6 `vertical_agent_templates` rows have empty `system_prompt_additions` and `tool_config = {}`.

There is no real curated content to faithfully carry over. The "migration" is a human decision about what each file should actually contain, not a mechanical data transfer.

## Goals / Non-Goals

**Goals:**
- One `BaseAgent` holding the tool-calling loop, tool dispatch, the `MAX_TOOL_CALLS` safety cap, hub_id-scoped `HubSpotDataPullClient` construction, and audit logging — identical for every vertical and every client, because the loop mechanics are forced by the Anthropic tool-use API shape, not a business concern.
- One subclass per vertical (6 files), each declaring that vertical's `SYSTEM_PROMPT_ADDITIONS` and any tool-config overrides as real class attributes/code.
- One subclass per client (starting with the 2 real ones), each declaring which HubSpot fields (standard or custom-object) its agent looks at, as real code — not a runtime database read.
- `run_client_agent(hub_id)` keeps its exact signature so `main.py`/`debug_api.py`/`live_verification.py` need no changes.
- Custom-object reach (`list_custom_objects`/`pull_custom_object`) added to `BaseAgent` — genuinely new regardless of this change, since a tenant's custom objects are runtime-discovered data no class can hardcode ahead of knowing them.

**Non-Goals:**
- Does not move Blu Mountain's own authored vertical framework text (`analysis_content`) into code. That table is a distinct, already-working content-ingestion concern — shared, unmodified, Blu-Mountain-authored text — not the "agent configuration" leadership's directive is about. Vertical agent classes keep reading it from the database exactly as `run_client_agent` does today.
- Does not remove or change `tenant_onboarding_profiles`/`profiling.py`/`onboarding.py` — they keep working exactly as before, as a discovery aid a human consults while deciding what to write into a client's file. They simply stop being read by the agent at runtime.
- Does not add an admin UI for authoring agent classes — same posture already taken for vertical template authorship before this change; a human edits a Python file and deploys, full stop.
- No infrastructure or credential duplication — still one shared Anthropic API credential, one deployment. This change is entirely about application code structure, not infrastructure.

## Decisions

**Package layout**: `gateway/frameworks/agents/`
- `base.py` — `BaseAgent`, an abstract base class. Required class attributes subclasses must set: `VERTICAL: str` (which `analysis_content` framework text to read), `SYSTEM_PROMPT_ADDITIONS: str`. Optional: `MAX_TOOL_CALLS: int` (defaults to the module constant). A client subclass additionally sets `HUB_ID: str` and `CONFIRMED_FIELDS: dict[str, list[str]]` (keyed by either a standard `CRM_OBJECT_TYPES` name or a custom object's discovered `objectTypeId` — same shape the now-abandoned `agent-field-scoping` design used for its DB-backed equivalent, just a class attribute instead of a table read). An empty/absent `CONFIRMED_FIELDS` entry for a given object type falls back to full live discovery, exactly matching today's behavior for a client with nothing curated.
- `verticals/saas.py`, `plg.py`, `marketplace.py`, `ecommerce.py`, `services_project.py`, `transactional.py` — one file per vertical, e.g. `class SaaSAgent(BaseAgent): VERTICAL = "saas"; SYSTEM_PROMPT_ADDITIONS = "..."`.
- `clients/*.py` — one file per client, e.g. `class BluMountainGumpperAgent(SaaSAgent): HUB_ID = "148997330"; CONFIRMED_FIELDS = {...}`.
- `registry.py` — `@register_client_agent` decorator populates a module-level `dict[str, type[BaseAgent]]`; `clients/__init__.py` imports every client module so each self-registers on import. `run_client_agent(hub_id)` becomes a thin wrapper: look up the registry, instantiate, call `.run()` (the method `BaseAgent` implements once, currently the body of today's `run_client_agent`).
  - *Alternative considered — one hand-maintained dict literal mapping hub_id to class, edited directly.* Rejected at ~50+ expected clients: every onboarding would edit the same shared file, a growing merge-conflict hotspot. Self-registration via decorator means a new client is purely an additive new file.
  - *Alternative considered — auto-discovery by scanning the `clients/` directory's filenames for hub_ids, no explicit registration at all.* Rejected: implicit filename-to-hub_id convention is more fragile and harder to grep/understand than an explicit decorator call sitting right next to the class it registers.

**Unknown hub_id behavior**: `run_client_agent` raises a clear `ValueError` if `hub_id` has no registered class — deliberately not falling back to a generic/default agent. A client without a real file simply cannot run yet, the same refusal posture `resolve_vertical_or_raise` already uses elsewhere in this project rather than silently guessing.

**Custom-object tools stay on `BaseAgent`, not per-vertical/per-client.** Discovering a tenant's real custom object schemas is inherently runtime, per-tenant HubSpot data — no class can hardcode a custom object's `objectTypeId` before it's been discovered at least once. `list_custom_objects`/`pull_custom_object` are added to every agent uniformly; a client's own `CONFIRMED_FIELDS` can reference a custom object's `objectTypeId` once a human has actually discovered and decided to hardcode it.

**Migrating the 2 real instances is authorship, not data transfer.** Both currently have zero confirmed-relevant fields; there's nothing to copy faithfully. `clients/blu_mountain_gumpper.py` (`148997330`, subclasses `SaaSAgent`) and `clients/blu_mountain_test_account.py` (`149094230`, subclasses `MarketplaceAgent` — corrected from the old, wrong `saas`-pointing instance row) are authored fresh, starting with `CONFIRMED_FIELDS = {}` (matching today's actual — not aspirational — state, which is "nothing curated yet"), with a code comment listing today's `needs_review` field names as candidates for a human to actually decide on, not silently treated as confirmed.

**`149094230`'s vertical is `marketplace`, `148997330`'s is `saas` — resolved directly by the user, correcting a real inconsistency.** `tenants.vertical` had been `NULL` for `149094230` despite its old `client_agent_instances` row pointing at the `saas` template — that row was simply wrong; the tenant was actually defined as `marketplace` earlier. Both corrected via `set_tenant_vertical` against the live database (`148997330` confirmed `saas`, `149094230` set to `marketplace`).

**Client classes may only add fields/objects, never override prompt behavior — a client-level `SYSTEM_PROMPT_ADDITIONS` override is not built in this change.** Verticals decide *how to think*; clients only supply *what's true about them*, preserving the same boundary the old DB model already drew (`vertical_agent_templates.system_prompt_additions` in the system prompt vs. `client_agent_instances.injected_documentation` — client facts — in the user message). Resolved directly by the user: no real client has been named that needs behavioral customization beyond field selection, and building that flexibility speculatively contradicts this project's own working convention against designing for hypothetical future requirements. This is not a permanent constraint: because a client class inherits from its vertical class, adding an optional per-client prompt-additions override later (e.g. `CLIENT_PROMPT_ADDITIONS`, defaulting to empty, appended after the vertical's own additions) is a small, additive change requiring no redesign of the base/vertical/client hierarchy — deferred until a real client actually needs it, not built ahead of one.

## Risks / Trade-offs

- **[Trade-off] Editing a client's fields now requires a code change and a deploy**, where the database version allowed a live update with no deploy. → Accepted directly by leadership's own directive; this is the explicit, known cost of choosing real code over data.
- **[Risk] ~50+ client files is a real, ongoing maintenance surface** even with loop mechanics shared. → Mitigated by keeping each client file minimal (a handful of class attributes, no logic), and by the self-registering pattern keeping onboarding additive rather than requiring a shared file edit per client.
- **[Risk] A bug in `BaseAgent` now affects every vertical and every client identically** (same as today's shared function, not a new risk) — the difference this change makes is that *behavioral configuration* (fields, prompt additions) is what's now separate, not the loop itself. → Unchanged risk profile from today; isolation and loop-correctness tests stay centralized on `BaseAgent` rather than duplicated per class.
- **[Risk] Losing runtime editability could regress the exact problem `separate-vertical-client-agents` was built to solve** (editing a vertical's guidance without a deploy). → Accepted as the explicit, named cost of this direction; not treated as an oversight.

## Migration Plan

1. Build `gateway/frameworks/agents/` alongside the existing DB-driven code — no behavior change yet, nothing removed.
2. Author the 6 vertical classes and the 2 real client classes.
3. Swap `run_client_agent`'s internals to the new registry-based path; confirm via the existing test suite plus new class-based tests.
4. Remove `vertical_templates.py`/`client_agent.py` and their tests; drop the two tables (idempotent `DROP TABLE IF EXISTS`, matching the `mcp_tokens` precedent already in `schema.sql`).
5. No rollback path once the tables are dropped and the modules removed — this is a one-way migration, matching how this project has always treated a genuinely superseded mechanism (e.g. the MCP Auth App teardown), not something kept "just in case."

## Open Questions

None remaining — both questions raised during scoping (149094230's vertical; whether clients can override prompt behavior) are resolved above.
