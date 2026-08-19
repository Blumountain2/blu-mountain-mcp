## Context

The project has one implementation-tracking change already in flight, `openspec/changes/implement-hubspot-mcp-server/`, with its own `tasks.md` organized into nine capability groups (`hubspot-oauth`, `token-vault`, `hubspot-data-pull`, `airtable-staging`, `sybill-ingestion`, `live-mcp-session`, `security-hardening`, `tenant-isolation`, deployment/docs). That grouping is a reasonable implementation structure, but it is not the spec's own structure, and several rounds of real-bug fixes (documented in that change's `design.md` decision log) were folded into whichever capability group seemed closest rather than checked back against the spec's own enumerated items. Two consequences of that drift motivated this audit:

- Spec Section 10 lists seven specific open items. `tasks.md` item 9.2 claims "all but one" of "the spec's open items" are resolved, but the six it actually lists (Sybill payload structure, Sybill delivery mechanism, `staff_auth.py`'s fate, Microsoft OAuth Proxy parity, HubSpot Public-vs-Private-App status, the Airtable base) are not the same six as the spec's actual items 1-3-4-5-6-7 (minus #2, since #2 doesn't appear in either). Two real spec open items (compliance regime, tenant count) have their real answers sitting in `context/Hubspot/IMPLEMENTATION_PLAN.md` instead, uncited from `tasks.md` at all.
- Verifying the spec's Section 3.1 storage-model table line by line against the actual code (rather than trusting `tasks.md` 2.5's checkmark) surfaced that the Postgres-backed access-token cache the spec requires as the multi-instance baseline was never built.

## Goals / Non-Goals

**Goals:**
- Verify every spec requirement (Sections 2-10) directly against running code, `.env.example`, and `schema.sql` — not against another tracking document's claim about itself.
- Produce one consolidated, spec-shaped to-do list (`tasks.md`) so "completed / needed / blocked" can be read against the spec's own structure, not reconstructed from three different docs.
- Surface real gaps this kind of direct verification catches that status-tracking-by-checkbox does not.

**Non-Goals:**
- Re-implementing or fixing anything this audit finds. Gaps found here (e.g. the Postgres-backed cache) become their own follow-up tasks, not inline fixes.
- Replacing `implement-hubspot-mcp-server`'s own tracking — that change remains the record of what was built and in what order; this audit is a point-in-time verification pass against the original spec, run once implementation reached the point where "are we actually done" became the live question.
- Re-opening decisions already made and recorded in the other change's `design.md` decision log (e.g. webhook-vs-polling for Sybill, Google-only for the live session's OAuth Proxy) — this audit cites those decisions as resolving specific spec items, it does not re-litigate them.

## Decisions

**Verify against code, not against `tasks.md`'s own checkmarks.** A checkbox marked `[x]` in an existing tracking doc is a claim, not evidence. Every requirement in this audit's `tasks.md` cites either a direct code/config location checked during this audit, a passing test, or (for genuinely external items) the specific blocker preventing verification — the same standard `CLAUDE.md`'s non-negotiables already hold the rest of this project to.

**Map spec Section 10's open items against `IMPLEMENTATION_PLAN.md`, not `tasks.md` 9.2.** `IMPLEMENTATION_PLAN.md`'s own numbered answer table (lines 146-155) directly answers the spec's seven items, sourced from the actual client conversation — item 5 (secrets platform) is explicitly recorded there as resolved only for MVP ("a single app-level key... now reopened for the real hosting environment"), a nuance `tasks.md` 9.2 doesn't carry at all.

**Record the Postgres-backed cache gap as `needed`, not `blocked`.** Unlike production hosting or a real client's Sybill traffic, nothing external prevents building `PostgresAccessTokenCache` today — the schema, the pool, and the `AccessTokenCache` interface it would implement already exist. It's a real, currently-open piece of buildable work, not something waiting on anyone else.

**Treat the metrics-pipeline gap as `needed` but low-severity.** The audit log already gives per-tenant, queryable observability; what's missing is a purpose-built aggregate/rate view (the spec's literal "metrics pipeline"), which matters for production monitoring but blocks nothing today, since a single local instance can be observed directly via `docker logs`/`audit_log` queries, which is exactly how every issue found this session was actually diagnosed.

**Decided 2026-08-17, during apply: defer the metrics pipeline, confirmed the `SYBILL_WEBHOOK` rotation.** Two of this audit's open items needed a decision or a fact only the user could supply, not more code: (1) the client's `SYBILL_WEBHOOK` secret, flagged for rotation in `implement-hubspot-mcp-server` tasks.md 7.4 after a since-fixed test-output leak, was confirmed already rotated; (2) a dedicated metrics/rate-monitoring pipeline (spec Section 9) was deliberately deferred rather than built now, since nothing today depends on it — a single local instance, diagnosed via logs and `audit_log` queries all session — revisit once production monitoring actually matters.

## Risks / Trade-offs

- **[Risk] This audit's own findings could themselves go stale the same way `tasks.md` 9.2 did**, if a future change updates code without updating this audit's `tasks.md`. → Mitigation: this is a point-in-time verification, not a live-tracking replacement; `implement-hubspot-mcp-server/tasks.md` remains the doc every future change updates as it lands. This audit's value is the verification method (check the spec directly) more than the artifact staying current forever.
- **[Trade-off] No new specs/ delta files are produced**, since no spec-level requirement is changing. This means `openspec apply` on this change is really "do the two follow-up tasks this audit found," not a typical feature build — acceptable since that's what an audit change should produce.
