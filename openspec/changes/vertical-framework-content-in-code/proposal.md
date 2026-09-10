## Why

`analysis-template-schema` requires the six vertical frameworks, the operational skill, and the runtime prompt to be stored in Postgres (`analysis_content`) and read at request time via `frameworks/store.py::get_latest()`. `frameworks/ingest.py`'s `ingest_directory()` is a manual, human-run CLI command — not wired into `main.py`, `docker-compose.yml`, or any startup hook. A fresh deploy, or any environment where that manual step is skipped, has no framework/skill/prompt content in the database at all, and every diagnostic run (`openspec/changes/vertical-diagnostic-agent`) fails at request time with `NoDiagnosticPromptContent` — a real, forgettable operational risk, not a hypothetical one. After being shown the alternative's own real tradeoff (this content becomes part of git history and the built Docker image, permanently, rather than staying in a gitignored directory as today), the explicit decision is to eliminate the risk entirely by embedding the content as Python code, accepting that tradeoff.

## What Changes

- Each vertical's real framework document is embedded verbatim as a `FRAMEWORK_TEXT` class attribute directly in its `gateway/frameworks/agents/verticals/*.py` file, generated from the real source document by a new maintenance script (`gateway/scripts/embed_framework_content.py`) rather than typed by hand.
- The vertical-agnostic operational skill and runtime prompt are embedded the same way, as `OPERATIONAL_SKILL_TEXT`/`RUNTIME_PROMPT_TEXT` constants in a new shared `gateway/frameworks/agents/content.py` (shared across all six verticals rather than duplicated into each).
- `BaseAgent.__init__` now requires `FRAMEWORK_TEXT` to be set (the same pattern already used for `VERTICAL`/`HUB_ID`), refusing to construct otherwise — the missing-content failure mode moves from a runtime `NoDiagnosticPromptContent` exception at first diagnostic request to a clear, immediate construction-time error that can never depend on database state.
- `BaseAgent._system_prompt()` (the gather phase) and `diagnostics.py::produce_diagnostic_report()` (the diagnostic phase) both read these Python constants directly; neither calls `frameworks.store.get_latest()` anymore.
- **BREAKING**: `analysis-template-schema`'s non-negotiable that this content is stored in and served from Postgres no longer holds for the agent hierarchy's own use of it — the spec delta below narrows that requirement to the content this project doesn't yet have a code-embedding path for (Challenge Library, Operating Principles, Template Library), which are unaffected and remain exactly as they were.
- `frameworks/store.py`, `frameworks/ingest.py`, and the `analysis_content` table are otherwise untouched — this change does not remove the ingestion pipeline or stop it from also holding a copy of the framework/skill/prompt content; it only stops the agent hierarchy from depending on that copy at runtime.

## Capabilities

### Modified Capabilities
- `analysis-template-schema`: the requirement that vertical frameworks (and the operational skill/runtime prompt) are served to their consumer from Postgres at request time is narrowed to apply only to content without a code-embedding path; the agent hierarchy's own consumption of framework/skill/prompt content is now via embedded Python constants, regenerated from the same real source documents by a maintenance script rather than read from the database.
- `gateway-package-layout`: adds `gateway/frameworks/agents/content.py` (shared embedded skill/prompt constants) to the documented `frameworks/agents/` layout, and documents `gateway/scripts/embed_framework_content.py` as a maintenance script alongside the existing `frameworks/ingest.py`.

## Impact

- `gateway/frameworks/agents/verticals/*.py`: each vertical class gains a real, non-empty `FRAMEWORK_TEXT` class attribute (tens of KB of Blu Mountain's own delivered content per file).
- `gateway/frameworks/agents/content.py` (new): shared `OPERATIONAL_SKILL_TEXT`/`RUNTIME_PROMPT_TEXT` constants.
- `gateway/frameworks/agents/base.py`: `__init__` validates `FRAMEWORK_TEXT`; `_system_prompt()` reads `self.FRAMEWORK_TEXT` instead of `get_latest()`.
- `gateway/frameworks/agents/diagnostics.py`: `produce_diagnostic_report()` takes `framework_text` as an explicit parameter and reads the shared constants from `content.py`; no longer calls `get_latest()`.
- `gateway/scripts/embed_framework_content.py` (new): the maintenance script that regenerates the above from the real source documents whenever Blu Mountain delivers a revision.
- Tests: `tests/frameworks/agents/test_base.py`, `test_diagnostics.py`, `test_verticals.py`, `tests/session/test_live_session.py` updated to set/monkeypatch these constants directly instead of seeding `analysis_content`.
- **Confidentiality tradeoff, accepted explicitly**: Blu Mountain's real, delivered framework/skill/prompt content is now committed to this git repository and baked into the built Docker image, where previously it was deliberately excluded (gitignored source directory, original `.docx`/`.xlsx` files deleted after conversion). This is a one-way door for anything already committed.
