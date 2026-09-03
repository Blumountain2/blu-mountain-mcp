## Context

`gateway/frameworks/pull_agent.py` today implements exactly one shared, unpersisted agent per vertical: `run_pull_agent(hub_id, vertical)` builds a system prompt fresh on every call from `analysis_content`'s stored framework text, and a user message fresh on every call from `onboarding.get_latest_profile_for_tenant(hub_id)`. Nothing about "the agent" is ever stored — it's re-derived from scratch every run. This is the direct implementation of `analysis-model-templates/design.md`'s Non-Negotiable #6: *"No per-client infrastructure, deployment, or Anthropic API credential... One Anthropic API credential, one agent config per vertical, shared across every client of that vertical."*

That Non-Negotiable was not an unconsidered default. It was written after an earlier "build and train AI models per vertical, then per client" framing had already surfaced once and been explicitly corrected. This exact framing has now surfaced a second time (this change). Blu Mountain leadership has directed a deliberate reversal, confirmed in this change's own scoping conversation after the prior rejection and its stated reasoning were surfaced explicitly. This design implements that reversal — see Decisions below for what changes and why it's being treated as a considered supersession, not a silent contradiction.

Two supporting gaps, discovered while researching this change, block real per-client personalization regardless of the agent-architecture question:
- Whether `sync/hubspot_client.py::HubSpotDataPullClient.pull_crm_objects()`'s `SELECT hs_object_id, * FROM {TYPE}` already returns a portal's custom (non-standard) properties has never been confirmed. The one precedent on record (`context/BLOCKERS.md`) is that HubSpot's default `SELECT *` property set silently excluded `hs_object_id` itself until that was discovered and worked around — proof that "the default set is complete" cannot be assumed here either.
- The live session's `query_hubspot_data` tool (`gateway/session/live_session.py:319-384`) is one generic tool taking a free-text `object_type` string, with no way to scope a call to a client's own confirmed-relevant or custom fields.

## Goals / Non-Goals

**Goals:**
- Persist an independently-versioned agent template per vertical (six total), editable without a code deploy.
- Persist an independently-editable agent instance per client, built from its vertical's current template plus that client's own injected documentation.
- Confirm live, not assume, whether the existing pull path already returns custom HubSpot properties; close the gap if it doesn't.
- Decide and implement the shape of the live session's HubSpot query tool surface.
- Carry forward every isolation guarantee already proven for the single-layer version (`specs/vertical-pull-agent/spec.md`), now across two persisted layers instead of one ephemeral one.

**Non-Goals:**
- No per-client infrastructure, deployment, or Anthropic API credential. The reversal is about persisted per-client *configuration*, never duplicated infrastructure — one shared Anthropic API credential and one shared model continue to serve every vertical and every client, matching the "we only need 1 model" clarification this change was scoped around.
- No machine-learning training, fine-tuning, or model hosting — unchanged, still confirmed (by prior research against Anthropic/AWS Bedrock/Vertex AI documentation) to have no fitting path at this project's scale.
- No HubSpot write access, ever — unchanged project-wide rule.
- Does not build the three downstream analysis jobs (Funnel, Maintenance, KPIs & Reporting) — still out of scope per `HubSpot_MCP_Server_Spec_v1.2.md` Section 1.2, untouched by this change.
- Does not re-author or reformat Blu Mountain's six vertical frameworks — still their content, still ingested verbatim into `analysis_content`. A vertical *agent template* (this change) is this project's own configuration layered around that content, not a rewrite of it.

## Non-Negotiables

Carried forward from `analysis-model-templates/design.md`, still in force except where marked superseded:

1. No write operations against HubSpot, ever. **Still in force.**
2. No HubSpot Private App tokens. **Still in force.**
3. The three analysis jobs will not be built under this plan. **Still in force.**
4. The other Intelligence System inputs will not be ingested. **Still in force.**
5. No machine-learning training, fine-tuning, evaluation-dataset curation, or model hosting — ever, per client or per vertical. **Still in force**, and directly relevant here: this change adds per-client *configuration*, never per-client *training*. "AI agent per client" means a persisted prompt/context bundle, exactly as clarified in this change's own scoping conversation ("not blocked by the Anthropic API since we only need 1 model").
6. ~~No per-client infrastructure, deployment, or Anthropic API credential... one agent config per vertical, shared across every client.~~ **Superseded by this change.** Infrastructure and credential sharing stay unchanged (still one Anthropic API credential, still one deployment) — what's superseded is specifically "one agent config... shared across every client": this change persists one agent instance per client. See Decisions below.
7. Every multi-tenant code path still requires an isolation test before it's considered done. **Still in force**, and extended: the new `client_agent_instances` table needs the same structural-isolation test coverage already proven for `tenant_onboarding_profiles`.

## Decisions

**This is a knowing, documented supersession of Non-Negotiable #6, not a silent reversal.** The prior rejection happened twice, was based on real reasoning (a per-client copy was "functionally identical to the shared agent plus injected context" under the old ephemeral-context design, and confirmed no fine-tuning path existed regardless), and explicitly named its own reversal condition ("a genuine, structural reason the shared-agent approach can't isolate or serve one client correctly"). This change does not claim that condition was met — it proceeds on a direct leadership directive instead, made with full visibility into the prior rejection and its reasoning. `analysis-model-templates/design.md` should gain a short cross-reference note pointing here, so a future reader doesn't find two contradictory Non-Negotiables without an explanation of which one governs.

**Two-tier model: vertical template → client instance.**
- `vertical_agent_templates` (new table, versioned and append-only like `analysis_content`): one row per vertical per version — `vertical`, `version`, system-prompt additions layered on top of that vertical's raw framework text (tool-use guidance, prioritization instructions, style — this project's own configuration, not Blu Mountain's authored content), tool/model parameters (allowlist, `max_tool_calls`), `created_at`. Independently editable per vertical without touching another vertical's row or any code.
- `client_agent_instances` (new table, `hub_id`-scoped, `REFERENCES tenants(hub_id) ON DELETE CASCADE`): one row per client per version — `hub_id`, the `vertical_agent_templates` version it was built from, a snapshot of that client's injected documentation (onboarding-profile fields, confirmed custom fields, any client-specific notes), `created_at`. A genuine, durable per-client artifact — not context re-assembled on every call.

  *Alternative considered — fold this into `analysis_content`/`tenant_onboarding_profiles` instead of new tables.* Rejected: those tables' semantics are already load-bearing elsewhere (`analysis_content` promises shared, unmodified, Blu-Mountain-authored content; `tenant_onboarding_profiles` promises confirmed-relevant *fields*, not agent behavior). Overloading either would blur two genuinely different concerns and risk breaking existing consumers' assumptions about what those tables mean.

  *Alternative considered — persist only the client-level instance, skip a distinct vertical-template table, keep reading `analysis_content` directly for the vertical layer.* Rejected: the directive was explicitly "an AI agent per vertical layer as a template" as its own first-class, independently-editable thing — collapsing it back into the existing shared framework-content table would mean the vertical layer isn't actually unshared, only the client layer would be.

**How `pull_agent.py` changes.** `run_pull_agent(hub_id, vertical)` is replaced by `run_client_agent(hub_id)`: resolve `hub_id`'s current `client_agent_instances` row (producing one if absent, from its vertical's current `vertical_agent_templates` row plus a fresh onboarding-profile read), build the system prompt from the vertical template's additions layered over `analysis_content`'s raw framework text, and use the persisted instance's injected documentation as the client-specific half of the request. Blu Mountain's authored framework text itself is still never forked per client — what's now persisted per client is the *instance* wrapping it (this project's own configuration and that client's own confirmed documentation), consistent with the still-standing rule that authoring vertical-framework content stays out of this project's scope.

**Custom field access: confirm live before building anything new.** The `hs_object_id` precedent proves HubSpot's default `SELECT *` set can silently omit a field — it does not prove custom properties specifically are excluded. First step is a live check against a real test portal with at least one known custom property, directly observing whether the existing `SELECT hs_object_id, * FROM {TYPE}` already returns it.
- If yes: no pull-path change needed. The real gap is *discovery* (which of a tenant's returned properties are custom vs. standard, so an agent instance or query tool can specifically reference them) — a naming/metadata distinction added to the already-built `tenant-field-profiling` output, not a new HubSpot access path.
- If no: investigate whether HubSpot's MCP surface already exposes a schema/properties-listing tool before building one — `list_read_only_tools()`'s existing exclusion-logging (`gateway/sync/hubspot_client.py`) already buckets every tool it doesn't recognize or considers out-of-scope; that bucket needs inspecting for anything property/schema-shaped before assuming nothing exists (the same category of gap that hid `get_organization_details` until its exclusion bucket was actually read, per `CLAUDE.md`).

**`query_hubspot_data` → a small number of category-grouped tools, not a full per-type split.** HubSpot's own MCP surface exposes all 16 `CRM_OBJECT_TYPES` through one generic `query_crm_data` tool — there is no underlying per-type tool to mirror; any split is purely this project's own interface choice.
- *Option A — keep one generic tool.* Cheapest, but can't cleanly expose category-specific parameters (a deals-only stage filter, a custom-field allowlist that legitimately differs by object type) and doesn't improve the connecting model's ability to pick the right call beyond what the two existing `@mcp.prompt` functions already coach.
- *Option B — split into all 16 per-object-type tools.* Maximizes discoverability and per-type parameter precision, but bloats the tool list presented to every connecting session (16 schemas in context vs. 1), multiplies test/maintenance surface 16x, and most of the 16 share a near-identical shape (contacts/companies/deals/tickets/line_items/products all just want an optional property list) — not enough real behavioral difference to justify 16 separate definitions.
- *Option C — recommended: group into ~4 category tools*, mirroring how Blu Mountain's own documentation already segments HubSpot data: CRM Records (contacts/companies/deals/tickets/line_items/products), Engagement Records (calls/emails/meetings/notes/tasks), Marketing/Content (campaigns/landing_pages/blog_posts/segments), Users. Each exposes a category-appropriate `properties: list[str] | None` parameter — the hook custom-field access needs — while keeping the tool list short enough to stay legible in a connecting session, and only 4x's the maintenance surface instead of 16x.

  *Alternative considered — keep 1 tool, just add a `properties` parameter.* Rejected as the minimal fix: a single object-type-agnostic `properties` parameter can't express "these are valid custom fields for deals, not contacts" without the tool description itself becoming category-conditional logic dressed up as one tool — worse for the connecting model's own reasoning than genuinely category-scoped tools.

**Isolation carries forward across both new tables.** `client_agent_instances` gets the same structural `hub_id`-in-every-query pattern already proven for `tenant_onboarding_profiles` (a JOIN/WHERE clause enforced directly in the query, never a Python-level check a caller could skip). New isolation-test surface mirrors the existing onboarding-profile tests exactly, extended to the new table and to `run_client_agent`'s instance-resolution step.

## Risks / Trade-offs

- **[Risk] This reverses a Non-Negotiable explicitly reconfirmed twice before, and the project's own design history names this exact pattern as something that could "quietly become 'build both'."** → Mitigation: this document states the reversal explicitly and permanently as a supersession, not a silent contradiction; `analysis-model-templates/design.md` gets a cross-reference note pointing here.
- **[Risk] Real, ongoing N-times maintenance and isolation-testing surface** — six vertical templates plus one instance per client, growing with the client base, is exactly the cost the prior design explicitly avoided taking on. → Mitigation: none structural; this is the accepted cost of the directed reversal. Worth tracking in practice as the client count grows.
- **[Risk] Client agent instances can go stale** — a client's onboarding profile changes (a field gets reviewed, a vertical gets (re)assigned) but its persisted instance doesn't automatically reflect it. → Mitigation: instances are versioned, never mutated in place; "the current instance" always means the latest version, produced by an explicit regeneration step, not an assumption of permanence.
- **[Risk] The custom-field investigation could resolve either way, and the two branches are genuinely different scopes of work.** → Mitigation: `tasks.md` scopes the live-confirmation step as its own first task, gating everything downstream on its actual result.
- **[Trade-off] Category-grouped query tools are a real interface change** the two existing `@mcp.prompt` functions depend on. → Mitigation: both are updated in this same change; they already reference object-type concepts by convention rather than a hardcoded single tool name, so the update is mechanical, not a redesign.

## Migration Plan

- Additive only: `vertical_agent_templates` and `client_agent_instances` are new tables; no existing table (`tenants`, `tokens`, `analysis_content`, `tenant_onboarding_profiles`, etc.) is altered or migrated destructively.
- Backfill order: one `vertical_agent_templates` row per vertical first (bootstrapped from today's `pull_agent.py` system-prompt logic, so day-one behavior doesn't regress), then one `client_agent_instances` row per already-installed, vertical-assigned tenant.
- Rollout order: vertical templates → client instances (depends on templates existing) → the `query_hubspot_data` tool restructuring (independent of the agent-instance work; can ship separately, including last).
- Rollback: both new tables can be dropped without affecting any existing table or capability. Reverting `pull_agent.py`/`run_client_agent` to read `analysis_content` directly (today's behavior) is a straightforward code revert, not a data migration, if the new path needs to be backed out.

## Open Questions

- **Regeneration cadence**: should a client's agent instance regenerate automatically whenever its onboarding profile changes, or only on explicit request? Leaning toward explicit/manual, matching this project's existing human-review-checkpoint posture, but not decided here — revisit if manual regeneration proves too slow in practice.
- **Vertical template authorship**: staff-editable directly (like `tenants.vertical`), or authored through a review process closer to `analysis_content`'s ingestion? Leaning toward staff-editable, since these are this project's own configuration rather than Blu Mountain's authored content, but not decided here.
- **Custom-field scope**: whether closing the custom-field gap requires new HubSpot MCP Auth App scopes beyond what's already granted can't be answered until the live confirmation task (Decisions, above) actually runs.
