## Why

`HubSpot_MCP_Server_Spec_v1.2.md` explicitly places "the analysis jobs and dashboards that read from the Airtable staging layer," the remaining Intelligence System inputs (Slack, ClickUp surveys, business descriptions, architecture guides, RSS), and the Architecture Guide diffing out of scope (Section 1.2) — this project only ever built the pull-and-stage layer those jobs would consume. **This boundary was explicitly reconfirmed 2026-08-27** and this proposal is rewritten around it directly, rather than treating it as background context: everything in this document is either already finished, still to complete within that boundary, or explicitly excluded by it — see Non-Negotiables in `design.md` for the full excluded list and why each item is excluded.

The documentation this plan was originally blocked on has since been delivered by Blu Mountain (`context/Blu Mountain Documentation/`, gitignored, converted from the client's original files and verified complete). It describes the analysis approach differently than this plan first assumed: one shared, unmodified analysis workflow per business vertical (SaaS, PLG, Marketplace, E-commerce, Services/Project, Transactional — six verticals, already authored by Blu Mountain, not six things this project needs to write), parameterized per client at the moment a job eventually runs, rather than a separate persisted copy built and stored per client ahead of time. Storing and serving that content, and profiling each client's real fields against it, don't require the excluded jobs to exist — that's the work this proposal actually covers.

"AI model" here means a Claude prompt/agent configuration, not a trained or fine-tuned machine learning model — confirmed explicitly before this plan was first written, unchanged by the delivered documentation, and re-confirmed 2026-08-27 after an earlier framing ("build and train AI models per vertical, then per client") resurfaced: nothing in this design trains or fine-tunes anything, per client or per vertical. Per-client separation is a data/context-layer concern (see `design.md`'s Decisions), not a training concern.

## What's Finished

**The core sync service** (separate, already-complete change — `openspec/changes/implement-hubspot-mcp-server/`): multi-tenant HubSpot OAuth and encrypted token vault, the three real data-pull paths, the live Google-authenticated MCP session, Airtable staging, and Sybill call-transcript ingestion. 218 tests passing, confirmed live against real HubSpot, Google, and Airtable credentials — not just mocked.

**This change's Sections 1-4** (`tasks.md`):
- **Framework storage** — the six vertical frameworks plus `account-diagnostic-SKILL` and `Weekly_Diagnostic_Prompt` (8 pieces), ingested verbatim and versioned, append-only, independent of any tenant.
- **Tenant field profiling** — discovers which of a tenant's real HubSpot fields are actually populated, reusing the existing pull layer, cross-referenced against each framework's own trust/unreliable property guidance.
- **Tenant onboarding profiles** — a named, per-tenant, structurally isolated record of which fields are confirmed relevant, with a human-review checkpoint before a profile counts as final. Confirmed live 2026-08-25 against both real test portals, producing genuinely different results per tenant (8 vs. 14 populated fields).
- **Documentation and tracking** — `CLAUDE.md`/`BLOCKERS.md` updated to reflect this capability, test counts synced project-wide.

## New: The Vertical Pull Agent (confirmed in scope 2026-08-28)

Directive from Blu Mountain leadership: build an AI Agent per vertical (starting with SaaS) that automates constructing the HubSpot pull requests needed to gather that vertical's relevant data — replacing the current fixed, one-size-fits-all pull with one that's vertical-aware. Confirmed the same day: this stays strictly on the data-*gathering* side of the boundary — the agent decides what to pull, never what the data means. Analysis stays out of scope, per the reconfirmed boundary above.

"AI Agent" here means the Claude API's tool-use pattern — Claude selects and calls tools in a loop — not a trained or fine-tuned model. Confirmed by direct research against official Anthropic, AWS Bedrock, and Google Vertex AI documentation: no fine-tuning path exists for any current-generation Claude model that fits this project's scale (see `design.md`'s Decisions for the full findings). This is why the agent is built on prompting plus per-call context injection, the same mechanism as everything else in this plan, now actually using the `ANTHROPIC_API_KEY` already sitting in `.env` for the first time.

**Architecture**: one shared agent configuration per vertical (six total), never a copy per client. Per-client customization happens by injecting that client's onboarding profile and goals into each call, the same "shared instructions, isolated data" pattern the rest of this plan already uses. Per-client copies were considered and explicitly not adopted as the starting design — see `design.md`'s Decisions for why, and for the concrete, non-vague condition under which that fallback would actually be revisited.

The agent's tool surface is restricted to the existing allowlisted pull methods (`pull_crm_objects`, `pull_object`) — it gains no HubSpot access a human-written pull couldn't already reach, and every call still passes through the existing `_is_read_safe`/`_is_safe_select` checks. Isolation requirements are specified in `specs/vertical-pull-agent/spec.md`.

## What's Left, Within Scope

- **Ingest the eight delivered files never stored**: the six per-vertical Challenge Library documents, `Blu_Operating_Principles.md`, and the Template Library (`BluMountain_Template_Library_v1_3`) — pure storage/serving through the same mechanism already built, no new logic.
- **Persist a tenant's known vertical** as a staff-set field — `tenant-field-profiling` already assumes a tenant's vertical can be "known," but nothing today makes it knowable or stored; it's currently only ever a call-time parameter.
- **Roll onboarding-profile production out to every real installed portal**, using the full CRM object set rather than the 3-object subset used for the initial live confirmation.
- **Two questions that need Blu Mountain's own decision**, not blocked on anything technical: whether the Challenge Library documents need reformatting into Skill-format bodies, and what validation/testing methodology would prove a framework or the skill actually works (Blu Mountain's own documentation flags the latter as unsolved on their end too).

## What Will Not Be Implemented

See `design.md`'s **Non-Negotiables** section for the full list and the reasoning behind each: no HubSpot writes, no HubSpot Private App tokens, no build of the three analysis jobs (Funnel, Maintenance, KPIs & Reporting), no ingestion of the other Intelligence System inputs (Slack, ClickUp, business descriptions, architecture guides, RSS), no machine-learning training or fine-tuning of any kind, and no per-client infrastructure or per-client Anthropic API credential. These are not gaps in this plan — they are the original spec's own scope boundary, reconfirmed 2026-08-27, and stated here so nothing on this list is later assumed to be in progress. **Note the one thing that changed 2026-08-28**: the Anthropic API itself is no longer on this excluded list — the vertical pull agent above does use it, one shared credential across every client, never a per-client one. Training/fine-tuning stays excluded regardless; using the API to prompt a shared model is a different thing than training one, and only the latter was ever the actual boundary.

## Capabilities

### New Capabilities

- `analysis-template-schema`: storing and serving Blu Mountain's already-authored vertical frameworks, Challenge Libraries, operating principles, and template library (plus the operational skill and runtime prompt), versioned and referenceable independent of any one tenant. (Retained name from the original proposal; the capability itself is now ingestion/storage, not authoring — see `design.md`'s Decisions for why the name wasn't changed here.)
- `tenant-field-profiling`: discovering which of a tenant's real HubSpot fields are actually populated and in active use, informed by each framework's own default-trust/default-unreliable property guidance.
- `tenant-template-instantiation`: producing a named, tenant-specific onboarding profile — a runtime parameterization input, not a persisted copy of a framework or skill. (Retained name; see `design.md`.)
- `vertical-pull-agent` (added 2026-08-28): one shared, per-vertical AI agent (Claude API tool-use, not a trained model) that decides which existing allowlisted pull methods to call to gather that vertical's relevant HubSpot data — gathering only, never analysis. See `specs/vertical-pull-agent/spec.md`.

### Modified Capabilities

None — nothing about the existing HubSpot pull, Airtable staging, Sybill ingestion, or live session's behavior changes. This is new capability layered on top of what already exists, reading through the same pull mechanism, not altering it. (The pull agent *calls* the existing `pull_crm_objects`/`pull_object` methods on `sync/hubspot_client.py::HubSpotDataPullClient` — it doesn't modify them.)

## Impact

Mostly new code under `gateway/frameworks/`: no changes to `sync/`, `auth/`, `webhooks/`, or `session/` beyond the pull agent calling their existing public methods. New Postgres tables for the stored content, tenant vertical assignment, and tenant onboarding profiles. Reuses the existing HubSpot MCP Auth App connection and Postgres. **One new external dependency and one new config surface, added 2026-08-28 for the pull agent**: the `anthropic` Python SDK, and `ANTHROPIC_API_KEY` wired into `config.py` and `docker-compose.yml`'s `environment:` block (previously present in `.env` but unread by any code). No change to any existing HubSpot/Google/Airtable API surface, tool, or prompt. Building the three downstream analysis jobs, or ingesting any of the other excluded Intelligence System inputs, is explicitly out of this project's current scope — reconfirmed 2026-08-27, see `design.md`'s Non-Negotiables. Revisiting that would need its own scope decision and its own change, not an assumed follow-on to this one.
