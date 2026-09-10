## Context

`analysis-template-schema` was written for a system where framework/skill/prompt content is stored once in Postgres and read by any number of future consumers — a reasonable default when the actual consumer wasn't yet known. Now that the only real consumer is the agent hierarchy (`BaseAgent`'s gather phase, `diagnostics.py`'s diagnostic phase — confirmed by grepping the whole codebase: no other production code calls `get_latest(CONTENT_TYPE_FRAMEWORK/SKILL/PROMPT, ...)`), the DB-read indirection buys nothing except a manual, easily-forgotten step (`frameworks.ingest`) between "the content exists on disk" and "the agent can actually use it." This surfaced as a real question after the diagnostic phase (`vertical-diagnostic-agent`) went live: what happens on a fresh deploy where nobody ran the ingest command? Previously: every diagnostic request fails with `NoDiagnosticPromptContent`, discovered at the worst possible time (a staff member asking for a report).

The real documents live at `context/Blu Mountain Documentation/` — gitignored, with the original `.docx`/`.xlsx` files deleted after conversion (`context/BUILD_COMPARISON.md`), a strong signal of a deliberate choice to keep this content out of git and the built image. Baking it into `verticals/*.py`/`content.py` reverses that specifically for this content, a tradeoff discussed directly and accepted explicitly rather than assumed.

## Goals / Non-Goals

**Goals:**
- Eliminate the "someone forgot to run ingestion" failure mode entirely — a client agent class either has real content compiled in, or it cannot construct, full stop, with no database state in between.
- Keep the actual content byte-for-byte identical to the real delivered documents — no re-transcription, no risk of a copy-paste error. A generator script reads the real file and writes it as a Python string constant; nothing about the content itself is authored or edited by this project.
- Provide a clear, repeatable path to update this content when Blu Mountain delivers a revision (`scripts/embed_framework_content.py`), so this isn't a one-time hack that rots.

**Non-Goals:**
- This does not touch Challenge Library, Operating Principles, or Template Library content — those still live only in `analysis_content`, unaffected, since nothing in the agent hierarchy consumes them yet.
- This does not remove `frameworks/store.py`, `frameworks/ingest.py`, or the `analysis_content` table. They remain fully functional for the content they still serve; this change only stops the agent hierarchy from depending on them for framework/skill/prompt content specifically.
- This does not change what the diagnostic phase produces, its output shape, or its behavior in any way — confirmed live: the same real portals produce reports of the same quality and rigor before and after this change (see Migration Plan).

## Decisions

### Decision: A generator script transcribes content, not a person

`gateway/scripts/embed_framework_content.py` reads each real source document directly from disk and writes it into the corresponding Python file as a raw (`r"""..."""`) triple-quoted string constant, verified byte-for-byte identical to the source (`AST`-parsed and diffed against the original during this change's own implementation). No human transcribed or retyped any of Blu Mountain's real content at any point.

**Why raw strings:** none of the eight source documents (six frameworks, the skill, the prompt) contain a `"""` or `'''` sequence, confirmed by grep before choosing this approach; a raw string preserves backslashes literally (several documents contain them) without Python's normal string-escape processing raising warnings on sequences like `\|` that aren't valid escapes but appear in the source prose.

**Why preserve `SYSTEM_PROMPT_ADDITIONS` across regeneration:** the script reads a vertical file's *current* `SYSTEM_PROMPT_ADDITIONS` value (via `ast`, not by re-running Python import machinery) before overwriting the file, so a future human-authored addition to that field survives a later content refresh. Regeneration is meant to touch only `FRAMEWORK_TEXT`.

### Decision: `FRAMEWORK_TEXT` validated at construction, mirroring `VERTICAL`/`HUB_ID`

`BaseAgent.__init__` already refuses to construct without `VERTICAL`/`HUB_ID` set; `FRAMEWORK_TEXT` joins that same check. This means a vertical class with no embedded content (a bug, not an expected state now) fails immediately and loudly at the first attempt to run that vertical's agent, not lazily inside `_system_prompt()` or, worse, the diagnostic phase's first request.

### Decision: `diagnostics.py` takes `framework_text` as an explicit parameter, not a lookup

Rather than have `diagnostics.py` import each vertical class to find its `FRAMEWORK_TEXT` (which would create an import-order dependency between `diagnostics.py` and `verticals/`), `BaseAgent.diagnose()` — which already holds `self.FRAMEWORK_TEXT` — passes it straight through. `diagnostics.py` remains agnostic to how a caller obtained the text, the same separation of concerns it already had for `client_name`/`system_prompt_additions`.

**Alternative considered:** Have `diagnostics.py` import `frameworks.agents.verticals` and look up by vertical name. Rejected: this is a strictly worse version of the same lookup-by-name pattern this whole change is trying to get away from, just moved from Postgres to a Python dict.

## Risks / Trade-offs

- **[Risk] Blu Mountain's real, delivered methodology is now committed to git history and the built Docker image, where it was deliberately excluded before →** Mitigation: none available after the fact — this is accepted explicitly, not a side effect. If this ever needs to be reversed, the content would need to be removed from history (not just deleted from the current tree) and the Docker image rebuilt from a clean history; flagged here so a future reader understands this was a real, discussed tradeoff.
- **[Risk] A content update now requires a code change + review + deploy, not a document re-ingest →** Mitigation: `scripts/embed_framework_content.py` makes this a single command plus a git diff review, not a hand-edit — closer in effort to the old `frameworks.ingest` invocation than to a from-scratch code change.
- **[Risk] `analysis_content` and the code-embedded content could silently drift apart** (someone re-ingests a new framework version into Postgres without also running the embed script, or vice versa) **→** Mitigation: not solved by this change — flagged as an Open Question below, since the actual production behavior now comes exclusively from the embedded constants, making a stale `analysis_content` row harmless (unread) rather than actively wrong, but still worth a human decision on whether to keep both paths fed.

## Migration Plan

1. Land the generator script and regenerate all six vertical files plus `content.py` — no other code changes yet, so this step is purely additive (new files/attributes, nothing removed).
2. Wire `BaseAgent`/`diagnostics.py` to the new constants, removing the `get_latest()` calls.
3. Update tests to set/monkeypatch the new constants directly.
4. Full test suite (336 tests) must pass with no `analysis_content` seeding required for any agent-hierarchy test.
5. Live-verify against both real test portals: confirm `run_vertical_diagnostic` still produces a real, high-quality report and stages successfully — done, twice (once immediately after the code change, once again after the maintenance script's template was finalized), both producing reports of equivalent depth/rigor to the pre-change DB-backed version.

No rollback complexity beyond a normal revert of the commits — `analysis_content`'s existing rows are untouched, so nothing here is destructive to data.

## Open Questions

- Should `frameworks/ingest.py`'s `FILE_MAP` stop ingesting the now-unused-by-the-agent framework/skill/prompt entries (8 of its 16 entries), to avoid a future silent drift between the Postgres copy and the embedded one? Left as-is for this change — removing them touches `store.py`'s content-type validation and two test files for a purely cosmetic dead-data concern, not a functional one, and didn't seem worth bundling into this change's own scope.
