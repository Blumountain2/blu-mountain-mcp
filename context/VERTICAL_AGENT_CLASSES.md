# Vertical Agent Classes Runbook

Covers how to create, edit, and save a **vertical** agent — one of the six business-vertical classes under `gateway/frameworks/agents/verticals/`. See `context/CLIENT_AGENT_CLASSES.md` for the client-level equivalent, and `openspec/changes/client-vertical-agent-classes/design.md` for the full reasoning behind why this is real code and not a database row.

There is no admin UI for any of this. "Saving" a vertical agent means committing a Python file and deploying — this project deliberately traded the prior database-row version's live-editability for real, version-controlled, reviewable code. Say that plainly to anyone expecting an in-app editor; there isn't one.

## What a vertical class is

Six classes exist, one per business vertical, under `gateway/frameworks/agents/verticals/`:

| Vertical | File | Class |
|---|---|---|
| SaaS | `saas.py` | `SaaSAgent` |
| PLG | `plg.py` | `PLGAgent` |
| Marketplace | `marketplace.py` | `MarketplaceAgent` |
| E-commerce | `ecommerce.py` | `EcommerceAgent` |
| Services/Project | `services_project.py` | `ServicesProjectAgent` |
| Transactional | `transactional.py` | `TransactionalAgent` |

Each subclasses `BaseAgent` (`gateway/frameworks/agents/base.py`) and sets exactly two things:

- `VERTICAL` — the vertical's name, matching `frameworks.ingest.FILE_MAP`'s stored name exactly (note `services-project` is hyphenated in that mapping even though the file is `services_project.py`). This is what the class uses to look up its raw framework text from `analysis_content` — Blu Mountain's own authored vertical framework document, ingested verbatim, never edited here.
- `SYSTEM_PROMPT_ADDITIONS` — this project's own tool-use guidance, prioritization, or style instructions for that vertical, layered onto Blu Mountain's raw framework text in the system prompt. As of this writing every vertical's value is the empty string `""` — none was ever actually authored in the prior database-row version either, so there's nothing to lose by moving to code.

Everything else — the tool-calling loop, the two standard tools (`list_object_types`/`pull_object_type`) plus the two custom-object tools (`list_custom_objects`/`pull_custom_object`), the bounded tool-call safety cap, isolation, audit logging — lives once in `BaseAgent` and is identical for every vertical. A vertical class never touches any of that.

## Create a new vertical (if a 7th one is ever needed)

This project's six verticals are fixed by Blu Mountain's own delivered documentation (`frameworks.vertical.KNOWN_VERTICALS`, derived from `frameworks.ingest.FILE_MAP`). Adding a genuinely new vertical means:

1. Ingest its raw framework text into `analysis_content` first (`frameworks.store.ingest(CONTENT_TYPE_FRAMEWORK, "<new-vertical>", content)`) — a vertical class with nothing to read from `analysis_content` will raise `ValueError: No stored framework for vertical ...` the first time it runs.
2. Add `"<new-vertical>"` to `frameworks.ingest.FILE_MAP` so `KNOWN_VERTICALS` includes it.
3. Create `gateway/frameworks/agents/verticals/<new_vertical>.py`:
   ```python
   from ..base import BaseAgent

   class NewVerticalAgent(BaseAgent):
       VERTICAL = "<new-vertical>"
       SYSTEM_PROMPT_ADDITIONS = ""
   ```
4. Add a test case to `gateway/tests/frameworks/agents/test_verticals.py`'s `_VERTICAL_CLASSES` list — `test_every_known_vertical_has_its_own_agent_class` will fail otherwise, deliberately, so a new vertical can never be added to `KNOWN_VERTICALS` without a matching class going unnoticed.
5. Rebuild and redeploy.

## Edit an existing vertical's guidance

Edit `SYSTEM_PROMPT_ADDITIONS` directly in that vertical's own file — plain Python string, multi-line if needed. Nothing else changes; no version bump, no migration, no other vertical's file touched. Rebuild and redeploy for the change to take effect — every future agent run for every client of that vertical picks it up (there's no per-instance staleness the way the old database version could theoretically have, since every run reads the class fresh, not a snapshot).

Git history is the version history now — there's no in-app "prior version" to roll back to; `git log`/`git revert` on that one file is the equivalent of the old database's append-only versioning.

## What you cannot do here

- You cannot give one client of a vertical different `SYSTEM_PROMPT_ADDITIONS` than another client of the same vertical — that's deliberately not built (see `design.md`'s resolved decision on this). A vertical's behavioral guidance is uniform across every client of that vertical; only a client's own `CONFIRMED_FIELDS` (which HubSpot fields/objects it looks at) varies per client — see `context/CLIENT_AGENT_CLASSES.md`.
- You cannot edit a vertical's raw framework text here — that's Blu Mountain's own authored content in `analysis_content`, ingested verbatim through `frameworks.store.ingest`, out of scope for this file entirely.
