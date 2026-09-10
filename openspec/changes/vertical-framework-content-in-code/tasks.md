## 1. Generator script and content embedding

- [x] 1.1 Confirm no source document contains a `"""`/`'''` sequence (safe for raw triple-quoted embedding) and none end in a trailing backslash — checked directly against all 8 real files
- [x] 1.2 Write `gateway/scripts/embed_framework_content.py`: reads each vertical's real framework document plus the shared skill/prompt documents from a `--source-dir`, writes `FRAMEWORK_TEXT` into each `verticals/*.py` and the shared constants into a new `content.py`, preserving any existing `SYSTEM_PROMPT_ADDITIONS` value across a regeneration
- [x] 1.3 Run the script against the real `context/Blu Mountain Documentation/` directory; verify every embedded value matches its real source file byte-for-byte (AST-parsed and diffed, not eyeballed)
- [x] 1.4 Syntax-check all regenerated files (`python3 -m py_compile`)

## 2. Wire BaseAgent and diagnostics.py to the embedded constants

- [x] 2.1 Add `FRAMEWORK_TEXT: str = ""` to `BaseAgent`, validated in `__init__` alongside `VERTICAL`/`HUB_ID`
- [x] 2.2 `BaseAgent._system_prompt()` reads `self.FRAMEWORK_TEXT` directly; remove the `frameworks.store.get_latest()` call and its now-unused imports
- [x] 2.3 `diagnostics.py::produce_diagnostic_report()` takes `framework_text` as an explicit parameter; reads `OPERATIONAL_SKILL_TEXT`/`RUNTIME_PROMPT_TEXT` from the new `content.py` instead of calling `get_latest()`
- [x] 2.4 `BaseAgent.diagnose()` passes `framework_text=self.FRAMEWORK_TEXT` through to `produce_diagnostic_report()`
- [x] 2.5 `NoDiagnosticPromptContent` repurposed: raised only when a direct caller of `produce_diagnostic_report()` passes an empty `framework_text` (a real caller via `BaseAgent` can never hit this, since construction already refused)

## 3. Update tests

- [x] 3.1 `tests/frameworks/agents/test_base.py`: `_agent_class()`/`_seed_client()` set `FRAMEWORK_TEXT` directly instead of seeding `analysis_content`; replaced the "no stored framework" test with "a client class with no FRAMEWORK_TEXT refuses to construct"
- [x] 3.2 `tests/frameworks/agents/test_diagnostics.py`: rewritten to monkeypatch `diagnostics.OPERATIONAL_SKILL_TEXT`/`RUNTIME_PROMPT_TEXT` to short test strings and pass `framework_text` directly per call, instead of seeding `analysis_content`
- [x] 3.3 `tests/frameworks/agents/test_verticals.py`: rewritten to confirm each real vertical class has real, non-empty, distinct `FRAMEWORK_TEXT` and that it reaches the system prompt, instead of seeding `analysis_content` per test
- [x] 3.4 `tests/session/test_live_session.py`: the four throwaway `_TestAgent` classes used by `run_vertical_diagnostic` tests gained `FRAMEWORK_TEXT` so they can construct
- [x] 3.5 Full suite: 336 tests passed

## 4. Live verification

- [x] 4.1 Confirmed live against both real test portals (148997330 SaaS, 149094230 Marketplace) via `gateway/scripts/live_verification.py`: all 7 steps PASS, including a real `run_vertical_diagnostic` report generated entirely from embedded code content and staged to Airtable
- [x] 4.2 Confirmed the report's quality/rigor is unchanged from the pre-change DB-backed version (same framework logic, same data-adequacy floors correctly applied)

## 5. Documentation

- [x] 5.1 CLAUDE.md updated to describe the embedded-content architecture, the confidentiality tradeoff accepted, and the maintenance script
- [ ] 5.2 Archive this change once reviewed
