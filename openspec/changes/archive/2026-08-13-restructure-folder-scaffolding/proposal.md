## Why

The `gateway/` directory uses a flat module structure — all twelve production Python modules sit at the root level with no grouping. This obscures subsystem boundaries, makes dependency chains hard to trace, and will become unnavigable as additional integrations (Slack, Teams, Microsoft Graph) are added. Introducing functional subpackages aligns the file structure with the architectural subsystems already described in the spec and CLAUDE.md.

## What Changes

- Move production modules into four subpackages within `gateway/`: `auth/`, `sync/`, `webhooks/`, and `session/` (named `session/`, not `mcp/` — see design.md; a subpackage literally named `mcp` would shadow the real `mcp` SDK that `fastmcp` depends on)
- Retain `main.py`, `config.py`, `db.py`, `schema.sql`, and container files at the `gateway/` root — they are cross-cutting infrastructure with no natural subpackage home
- Add an `__init__.py` to each subpackage that re-exports the public surface (routers, entry-points, key classes), keeping `main.py` clean
- Mirror the subpackage layout in `gateway/tests/` so test discovery matches the production structure
- Update all internal import paths to reflect the new locations

## Capabilities

### New Capabilities
- `gateway-package-layout`: Canonical directory structure and subpackage organization for the gateway service; defines where each type of module lives and what belongs at the root vs. inside a subpackage

### Modified Capabilities
<!-- No spec-level requirement changes — this is a structural reorganization only -->

## Impact

- **gateway/**: twelve production modules reorganized into four subdirectories; no behavioral changes
- **gateway/tests/**: ten test modules reorganized to mirror the new subpackage layout; conftest.py and cross-subsystem security tests remain at `tests/` root
- **Import paths**: all internal `from <module> import ...` statements updated in `main.py` and test files
- **No API changes**: routes, request/response shapes, and external interfaces are unchanged
- **No dependency changes**: `requirements.txt` and `Dockerfile` are unaffected
