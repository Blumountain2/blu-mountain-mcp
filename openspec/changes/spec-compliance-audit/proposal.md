## Why

Implementation has been tracked against `openspec/changes/implement-hubspot-mcp-server/tasks.md`, which reorganized the original spec (`context/Hubspot/HubSpot_MCP_Server_Spec_v1.2.md`) into its own capability groupings over several months of work. That reorganization has drifted from the spec's own section structure and enumerated items (its Section 10 "Assumptions and Open Items" in particular is not the same list `tasks.md`'s own item 9.2 checks off). A fresh, section-by-section reconciliation directly against the spec text — not against a downstream tracking doc that summarizes it — is needed before onboarding a real client, so that what's actually completed, needed, or blocked is known with certainty rather than inherited from prior status claims. This audit already surfaced two real gaps that no existing tracking doc had recorded (see `design.md`).

## What Changes

- Walk every numbered requirement in the spec (Sections 2-10: Authentication Architecture, Multi-Tenant Token Management, MCP Server Connection, Tenant Isolation, Security Controls SC-1–SC-10, Functional Requirements FR-1–FR-13, Non-Functional Requirements, Reference Stack, Assumptions/Open Items 1-7) and verify each directly against the running code and `.env.example`/`schema.sql`, not against `tasks.md`'s claims about itself.
- Record two real, previously-undocumented gaps found in the process:
  - The Postgres-backed access-token cache the spec requires as the multi-instance baseline (Section 3.1) was never built — only `InMemoryAccessTokenCache` exists, and it's the only implementation `TokenVault` can use.
  - No metrics pipeline exists separate from the audit log and structured logs (Section 9's Observability row calls for "audit logs **and** metrics pipeline" as two things).
- Reconcile spec Section 10's seven open items against `context/Hubspot/IMPLEMENTATION_PLAN.md`'s actual recorded client answers, since `tasks.md`'s 9.2 checklist references a different, non-overlapping set of "open items" than the spec's own seven and doesn't surface that item 5 (secrets-management platform) was resolved only for local/MVP use and is explicitly reopened for the production hosting environment (matching `context/BLOCKERS.md` blocker #2).
- Produce one consolidated tasks.md classifying every requirement as done, needed, or blocked, each with a direct citation to the verifying code/test/doc.
- No runtime code changes in this change itself — any gap this audit surfaces (e.g. the Postgres-backed cache) is scoped as its own follow-up task, not fixed inline here.

## Capabilities

### New Capabilities

None — this is a documentation/audit change, not new system behavior.

### Modified Capabilities

None — no spec-level requirement is being changed by this audit itself.

## Impact

Read-only review across `gateway/` (all subpackages), `openspec/changes/implement-hubspot-mcp-server/*.md`, `context/BLOCKERS.md`, `context/Hubspot/IMPLEMENTATION_PLAN.md`, `.env.example`, and `gateway/schema.sql`, against `context/Hubspot/HubSpot_MCP_Server_Spec_v1.2.md`. No production code, schema, or configuration is changed by this change.
