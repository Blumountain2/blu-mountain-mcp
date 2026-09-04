## Why

Several rounds of code review this project has already run (informal `/code-review` passes, not a formal change) identified real, verified duplication and dead-file cruft that was never actually fixed — either because it was explicitly out of the "confirmed bugs only" scope at the time, or because it's been sitting unaddressed since. Separately, the recent `client-vertical-agent-classes` migration left two root-level scripts genuinely broken (they import a module, `frameworks.client_agent`, that no longer exists) and left `context/DATABASE.md` describing two database tables that were dropped outright. This change cleans up both classes of debt in one pass, re-verifying every item against the current code first rather than trusting the earlier findings blindly.

**Explicit boundary, stated directly by the user**: `gateway/frameworks/agents/**` (the vertical/client agent class hierarchy) is deliberately untouched by this change. Only old scripts/files *for the prior, now-deleted shared-agent system* are in scope for removal there — not the current agent code itself.

## What Changes

- Remove two root-level scripts left over from the prior shared-agent architecture, now genuinely broken (not just redundant): `shared_client_test.py`, `show_concurrent_isolation.py` (already removed as part of scoping this change — see tasks.md).
- Correct `context/DATABASE.md`'s `vertical_agent_templates`/`client_agent_instances` sections, which describe two tables that no longer exist.
- Collapse the repeated `owns_client = client is None` / resolve-then-teardown pattern copy-pasted across 6 methods in `sync/hubspot_client.py` into one shared helper.
- Collapse three near-identical one-line adapter methods (`_pull_campaigns_as_records`, `_pull_landing_pages`, `_pull_blog_posts`) into one path-keyed method.
- Factor the tenant display-name fallback query (duplicated verbatim across `live_session.py`, `debug_api.py`, `onboarding.py`) into one shared function.
- Factor the free-text object-type alias resolution logic (duplicated between `debug_api.py` and `live_session.py`) into one shared function.
- `debug_api.py`'s installed-tenant check reuses `auth.token_vault.get_installed_hub_ids()` (the project's own documented single source of truth for this) instead of hand-writing an equivalent query.
- `debug_api.py`'s duplicated comma-separated `properties=` parsing (two call sites) becomes one shared helper.
- `debug_api.py`'s fake-instance construction (`HubSpotDataPullClient("").list_read_only_tools()`) — calling a method that ignores `hub_id` by instantiating a client with a placeholder empty one — becomes a plain function call instead.
- `onboarding.py`'s per-field, one-row-at-a-time `INSERT` inside `produce_onboarding_profile` becomes one batched insert.
- `live_session.py`'s `_query_category` validates the requested object type is in-category *before* resolving a vault token/HTTP connection, instead of paying that cost on a request that turns out to be invalid anyway.

**No behavioral change is intended anywhere in this list** — every item is either dead/broken code removal, or an internal refactor expected to produce identical external behavior, verified by the existing test suite passing unchanged.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `gateway-package-layout`: gains a requirement that internal duplication may be found and removed at any time, provided it never changes external behavior and an explicitly-scoped exclusion (like `gateway/frameworks/agents/**` here) is respected — codifying a pattern this project has already re-derived twice informally (two prior code-review passes), rather than a new behavior.

## Impact

- Removed: `shared_client_test.py`, `show_concurrent_isolation.py` (root).
- Edited: `context/DATABASE.md`, `gateway/sync/hubspot_client.py`, `gateway/debug_api.py`, `gateway/session/live_session.py`, `gateway/frameworks/onboarding.py`.
- Explicitly not touched: `gateway/frameworks/agents/**`, `gateway/frameworks/pull_agent.py`.
- No schema, API, or test-behavior changes expected — the full existing test suite must still pass unchanged, proving this.
