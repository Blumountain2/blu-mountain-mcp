## Why

Leadership direction (this change's own scoping conversation) is that vertical and client agent configuration must be real, separate, version-controlled **code** — not database rows a runtime lookup assembles. This is a deliberate, further reversal beyond what `separate-vertical-client-agents` already reversed: that change persisted per-vertical/per-client *configuration* as data specifically so it could be edited without a code deploy; this change reverses that specific tradeoff, accepting a code deploy per edit in exchange for each vertical and each client being genuinely separate, reviewable, version-controlled implementations rather than rows assembled by one shared function at runtime.

## What Changes

- **BREAKING**: `vertical_agent_templates` and `client_agent_instances` are dropped entirely. `gateway/frameworks/vertical_templates.py` and `gateway/frameworks/client_agent.py` are removed.
- **BREAKING**: `run_client_agent(hub_id)`'s internals are replaced — a real class hierarchy (`BaseAgent` → one subclass per vertical → one subclass per client) replaces the DB-row-driven system prompt/config assembly. A thin, same-signature wrapper is kept so existing call sites (`main.py`, `debug_api.py`, `gateway/scripts/live_verification.py`) don't need to change.
- New `gateway/frameworks/agents/` package: `base.py` (the shared loop mechanics — the tool-calling while-loop, tool dispatch, the `MAX_TOOL_CALLS` safety cap, audit logging, hub_id-scoped isolation — identical for everyone because the Anthropic tool-use API shape forces it, not a business decision), `verticals/*.py` (6 files, one per vertical), `clients/*.py` (one file per client, starting with the 2 real ones already installed).
- Each client's own file declares, as real code: which HubSpot fields (standard or custom-object) its agent looks at, replacing `tenant_onboarding_profile_fields`'s runtime read.
- Custom-object reach (`list_custom_objects`/`pull_custom_object` tools) is added to `BaseAgent` directly — this piece was never DB-driven to begin with, it's new regardless of the code-vs-data question, and every client/vertical gets it since custom-object discovery is inherently per-tenant runtime data no class can hardcode ahead of time.
- `tenant_onboarding_profiles`/`profiling.py`/`onboarding.py` are kept, unchanged, as a discovery aid a human consults *while writing* a new client's file — they stop being read by the agent at runtime.
- Two new operator runbooks describing the real, code-based workflow: creating/editing a vertical's agent class, and creating/editing a client's agent class (including registering it so `run_client_agent` can find it).

## Capabilities

### New Capabilities
- `client-vertical-agent-classes`: one shared agent-loop base class, one subclass per vertical, one subclass per client — real, separate, version-controlled implementations instead of database-row-driven configuration.

### Modified Capabilities
- `vertical-pull-agent`: the requirement "resolves a persisted vertical template and client instance before running" (added by `separate-vertical-client-agents`) is superseded — the agent now resolves a *class* via a registry, not a database row.

## Impact

- `gateway/frameworks/agents/` (new package: `base.py`, `verticals/`, `clients/`, `registry.py`).
- `gateway/frameworks/pull_agent.py` — `run_client_agent` becomes a thin registry-lookup wrapper; `_TOOLS`/`_bind_tool_executor`'s logic moves into `BaseAgent`.
- Removed: `gateway/frameworks/vertical_templates.py`, `gateway/frameworks/client_agent.py`, and their tests.
- `gateway/schema.sql` — `DROP TABLE IF EXISTS vertical_agent_templates`, `DROP TABLE IF EXISTS client_agent_instances` (idempotent, matching the existing `mcp_tokens` drop precedent).
- The 2 real, already-produced instances (`148997330`, `149094230`) get hand-authored into real client files as part of this change — both currently have zero confirmed-relevant fields and empty template additions in the database, so there is no real curated content to carry over faithfully; a human still has to decide what each file should actually contain.
- `main.py`, `gateway/debug_api.py`, `gateway/scripts/live_verification.py` — no call-site changes, `run_client_agent(hub_id)` keeps its signature.
- Two new docs: how to create/edit/save a vertical agent class, and a client agent class.
