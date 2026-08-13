## Context

The `gateway/` service currently holds all twelve production Python modules in a single flat directory. The modules represent four distinct subsystems — OAuth + token vault (`auth`), scheduled data sync (`sync`), webhook ingestion (`webhooks`), and interactive MCP sessions (`session`) — but nothing in the filesystem reflects that grouping. Cross-cutting infrastructure (`main.py`, `config.py`, `db.py`, `schema.sql`) sits alongside domain-specific code with no visual separator.

The HubSpot MCP Server spec (v1.2) defines these subsystems architecturally. The refactor makes the code layout match the architecture, no more, no less.

## Goals / Non-Goals

**Goals:**
- Group domain modules into four subpackages: `auth/`, `sync/`, `webhooks/`, `session/`
- Keep infrastructure files (`main.py`, `config.py`, `db.py`, `schema.sql`, `Dockerfile`, `requirements*.txt`) at the `gateway/` root
- Expose each subpackage's public surface through an `__init__.py`, so `main.py` imports from a stable location rather than from individual module files
- Mirror the subpackage layout in `gateway/tests/`; keep cross-subsystem security tests at `tests/` root

**Non-Goals:**
- No behavioral changes, API changes, or route changes of any kind
- No changes to `requirements.txt`, `Dockerfile`, or `docker-compose.yml`
- No changes to `schema.sql` or the Postgres schema
- Not a code quality pass — no refactoring of logic, naming, or patterns inside modules

## Decisions

**Decision: Four subpackages, not more**

The four subpackages (`auth/`, `sync/`, `webhooks/`, `session/`) map directly to the four architectural subsystems in CLAUDE.md and the spec. Splitting further (e.g., separating `crypto.py` from `security.py` into a `core/` package) would add nesting without capturing a real subsystem boundary. Fewer levels is easier to navigate.

**Decision: Infrastructure at root, not in a `core/` package**

`main.py`, `config.py`, `db.py`, and `schema.sql` are used by every subsystem. Wrapping them in a `core/` or `shared/` package would require every subpackage to import from `..core`, adding path indirection that obscures rather than clarifies. Keeping them at root makes their cross-cutting role explicit.

**Decision: `__init__.py` re-exports, not wildcard imports**

Each subpackage `__init__.py` explicitly re-exports the symbols that `main.py` (and tests) need — routers, scheduler entry-points, key classes. This keeps `main.py` clean (`from auth import router as auth_router`) without exposing internal helpers. Wildcard imports (`from auth import *`) would make it impossible to know what the public interface is.

**Decision: Fourth subpackage named `session/`, not `mcp/` (revised during implementation)**

Originally planned as `mcp/`, matching the "interactive MCP session" terminology. Discovered empirically during implementation: this project depends on `fastmcp`, which itself depends on the official `mcp` PyPI SDK, imported internally as `import mcp.types` etc. Because the gateway root is prepended to `sys.path` ahead of site-packages, a local subpackage literally named `mcp` shadows that real dependency — confirmed by the container failing to start with `ModuleNotFoundError: No module named 'mcp.types'` / `ImportError: FastMCP server support is not installed.`. `session/` avoids the collision while still describing the subsystem (the live interactive session plus the direct staff-auth surface it sits beside).

**Post-completion note: `cowork_session.py` was later renamed to `live_session.py`.** This happened during the separate `implement-hubspot-mcp-server` change, not this one — the project's terminology shifted from "Cowork session" to "live session" once it was clear the same session serves Claude Desktop, Claude Code, and Claude Cowork identically, not a Cowork-specific feature. The migration plan and task list below still say `cowork_session.py` since that was the accurate filename at the time this restructure actually ran; `specs/gateway-package-layout/spec.md`'s scenario has been updated to the current filename, since that document makes an ongoing claim about the current structure, not a historical record of one move.

**Decision: Tests mirror production structure**

`tests/auth/`, `tests/sync/`, `tests/webhooks/`, `tests/session/` mirror their production counterparts. Cross-subsystem tests (`test_tenant_isolation.py`, `test_credential_hygiene.py`) stay at `tests/` root since they exercise multiple subsystems simultaneously.

## Risks / Trade-offs

**Import churn touches every file** → The move updates import paths in `main.py` and all ten test modules. Run `pytest` immediately after each subpackage move to catch broken imports before proceeding to the next. Move one subpackage at a time; do not batch all four in one commit.

**In-flight work on the same files** → Anyone working on a gateway module during this refactor will face merge conflicts. This change should land as a single PR with no other work touching `gateway/` in parallel. Coordinate the merge window before starting.

**`pytest.ini` discovery path** → `gateway/pytest.ini` currently discovers tests under `tests/`. After reorganizing `tests/` into subdirectories, confirm that pytest's `testpaths` and `python_files` settings still pick up all test modules. No change to `pytest.ini` is expected to be necessary, but verify.

**`tests/<subpackage>/` name collision with production packages** → discovered during implementation: pytest's default (`prepend`) import mode walks up from each test file to the first ancestor directory lacking an `__init__.py` and inserts *that* directory at `sys.path[0]`. Before this change, `tests/` had no `__init__.py`, so once `tests/auth/` was created, pytest inserted `/app/tests` ahead of `/app` — meaning `import auth` inside any test resolved to `tests/auth/` instead of the real `gateway/auth/` package (`ImportError: cannot import name 'vault' from 'auth' (.../tests/auth/__init__.py)`). Fixed by adding an empty `gateway/tests/__init__.py`, which makes pytest walk up past `tests/` to `gateway/` (the actual root without an `__init__.py`) before inserting a path, so `auth`/`sync`/`webhooks`/`session` resolve to the production packages, not the same-named test subdirectories.

## Migration Plan

Execute subpackage-by-subpackage, in this order, so the codebase stays runnable between steps:

1. **`auth/`** — `crypto.py`, `security.py`, `hubspot_oauth.py`, `token_vault.py`
2. **`sync/`** — `hubspot_client.py`, `airtable_staging.py`
3. **`webhooks/`** — `sybill_webhook.py` (rename to `sybill.py` inside the package)
4. **`session/`** — `cowork_session.py`, `staff_direct_auth.py` (rename to `staff_auth.py`)

For each subpackage:
1. Create the directory and a minimal `__init__.py`
2. Move the module files in
3. Update all `import` / `from` statements in the moved files
4. Update `main.py` to import from the subpackage
5. Reorganize matching test files into the mirrored `tests/<subpackage>/` directory and update their imports
6. Run `docker compose up` and `pytest` — must be green before moving to the next subpackage

**Rollback**: Because this is a series of file moves with no behavioral changes, rollback is `git revert`. No database migrations, no config changes, no deployment steps are involved.

## Open Questions

- ~~**`staff_direct_auth.py` placement**: The CLAUDE.md notes that whether the direct JWT path remains distinct from the Cowork/FastMCP path is an open question. It is placed in `session/` here on the grounds that it is a staff-access surface, not an auth infrastructure module. If the decision later resolves to supersede it entirely, the module is deleted from wherever it lives; the subpackage location does not affect that decision.~~ **Resolved in `implement-hubspot-mcp-server`'s decision log: kept, but unhooked from `main.py`** (no planning document identified a consumer for it distinct from the live session). The module (`session/staff_auth.py`) stays exactly where this change placed it — the open question was about whether it's still needed, not where it lives, and that's settled without moving it.
