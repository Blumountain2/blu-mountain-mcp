## Why

Every vertical today shares one hardcoded agent (`gateway/frameworks/pull_agent.py`), and every client of a vertical shares that same agent's system prompt, re-assembled fresh on every run with no persisted, independently-editable identity of its own. Blu Mountain leadership has directed the opposite: each vertical should have its own independently maintainable agent template, and each client should get its own agent instance built from that template plus documentation specific to that client's own fields and needs — not a config re-derived from scratch every call. This is a deliberate reversal of `analysis-model-templates/design.md`'s Non-Negotiable #6 ("no per-client... agent config"), made explicitly and with the historical rejection of this exact framing on record — see this change's `design.md` for the reasoning.

Two supporting gaps block real per-client personalization regardless of the agent-architecture question: this project has never confirmed whether its HubSpot pull path returns a portal's *custom* properties at all, and the live session's one generic `query_hubspot_data` tool has no way to scope a call to a client's own confirmed-relevant fields.

## What Changes

- **BREAKING** (supersedes a documented Non-Negotiable): move from one shared, unpersisted agent config per vertical to a two-tier model — a persisted, independently-versioned **vertical agent template** (six total, one per vertical), and a persisted, independently-editable **client agent instance** built from that template plus that client's own injected documentation (onboarding profile, confirmed custom fields, business context where available).
- Retire `pull_agent.py`'s single hardcoded system-prompt-per-call-parameter pattern in favor of reading a vertical's own persisted template and a client's own persisted instance.
- Confirm live whether `HubSpotDataPullClient.pull_crm_objects()`'s `SELECT * FROM {TYPE}` already returns a portal's custom (non-standard) properties, or only HubSpot's default property set (the existing `hs_object_id` precedent — excluded from `SELECT *` by default — means this cannot be assumed either way).
- Build MCP tooling to discover and explicitly pull a portal's custom fields if the above confirms `SELECT *` doesn't already cover them.
- Restructure the live session's single generic `query_hubspot_data` tool into a small number of category-scoped tools (grouping, not a full 16-way split — see `design.md`), each able to be scoped to a client's own confirmed-relevant fields via its onboarding profile.
- Unchanged: no HubSpot write access, no ML training or fine-tuning of any kind, one shared Anthropic API credential (per-client means per-client *configuration*, never per-client infrastructure or a per-client API credential), structural `hub_id` isolation on every new table.

## Capabilities

### New Capabilities
- `vertical-agent-templates`: persisted, independently-versioned agent configuration per vertical (system-prompt additions beyond the raw framework text, tool restrictions, model/loop parameters), editable per vertical without a code deploy.
- `client-agent-instantiation`: producing and persisting one agent instance per client, built from its vertical's current template plus that client's own injected documentation — a genuine, durable per-client artifact, not context assembled fresh per call.
- `hubspot-custom-field-access`: confirming and, if needed, building the pull-path mechanism for a portal's custom (non-standard) HubSpot properties, and surfacing which custom fields exist per tenant.
- `hubspot-query-tool-surface`: the live session's HubSpot data-query tool(s) — the investigated, decided shape (category-grouped tools rather than one generic tool or a full per-object-type split) and how each tool scopes to a client's confirmed-relevant fields.

### Modified Capabilities
- `vertical-pull-agent`: requirements change from "one shared agent config per vertical, reused across every client, explicitly no per-client persisted config" to "a per-vertical template plus a per-client persisted instance built from it." The isolation requirements (context assembly, tool-call binding, concurrent-run isolation, audit attribution) carry forward unchanged in spirit but now apply across two persisted layers instead of one ephemeral one.

## Impact

- `gateway/frameworks/`: `pull_agent.py` restructured; new modules for vertical-template storage/retrieval and client-agent-instance production, alongside the existing `store.py`/`onboarding.py`/`profiling.py`/`vertical.py`.
- New Postgres tables (`gateway/schema.sql`): vertical agent templates (versioned, append-only) and client agent instances (`hub_id`-scoped, `REFERENCES tenants(hub_id)`), following this project's existing structural-isolation and versioned-snapshot conventions.
- `gateway/sync/hubspot_client.py`: custom-field confirmation/access path.
- `gateway/session/live_session.py`: `query_hubspot_data` tool surface restructured into category-scoped tools; the two existing `@mcp.prompt` functions updated to reference the new tool names.
- New isolation tests for the client-agent-instance layer, matching this project's standing per-multi-tenant-path requirement.
- No change to HubSpot OAuth, the token vault, Airtable staging, or Sybill ingestion. No new external dependency — reuses the existing `anthropic` SDK and `ANTHROPIC_API_KEY`.
