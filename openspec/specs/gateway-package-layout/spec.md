# gateway-package-layout Specification

## Purpose
The gateway service's own code organization — subpackages by concern (`auth/`, `sync/`, `webhooks/`, `session/`), infrastructure modules kept at the package root, each subpackage's public surface expressed through its own `__init__.py`, and tests mirroring that same structure — with no behavioral change expected from the layout itself.
## Requirements
### Requirement: Gateway subpackage structure
The gateway service SHALL organize production domain modules into four functional subpackages within `gateway/`: `auth/`, `sync/`, `webhooks/`, and `session/`. Each subpackage SHALL contain only the modules belonging to its subsystem.

The fourth subpackage is named `session/`, not `mcp/`: this project depends on `fastmcp`, which itself depends on the official `mcp` PyPI SDK (imported internally as `mcp.types` etc). A local subpackage literally named `mcp` shadows that dependency on `sys.path` and breaks `fastmcp`'s own imports.

#### Scenario: auth subpackage contains auth modules
- **WHEN** a developer lists files in `gateway/auth/`
- **THEN** it contains `crypto.py`, `security.py`, `hubspot_oauth.py`, and `token_vault.py`, plus an `__init__.py`. Two further modules were added later, in `implement-hubspot-mcp-server`, on the same "this belongs in `auth/`" grounds this change established rather than as an exception to it: `mcp_auth.py` (a second OAuth install/callback flow, for the MCP Auth App credential — spec Section 4.1) and `pages.py` (the HTML success/error pages both install flows render).

#### Scenario: sync subpackage contains data sync modules
- **WHEN** a developer lists files in `gateway/sync/`
- **THEN** it contains `hubspot_client.py` and `airtable_staging.py`, plus an `__init__.py`

#### Scenario: webhooks subpackage contains webhook modules
- **WHEN** a developer lists files in `gateway/webhooks/`
- **THEN** it contains `sybill.py` (formerly `sybill_webhook.py`), plus an `__init__.py`

#### Scenario: session subpackage contains session modules
- **WHEN** a developer lists files in `gateway/session/`
- **THEN** it contains `live_session.py` (moved in as `cowork_session.py`; renamed during the `implement-hubspot-mcp-server` change to match this project's "live session" terminology, which serves Claude Desktop/Code/Cowork identically rather than being Cowork-specific) and `staff_auth.py` (formerly `staff_direct_auth.py`), plus an `__init__.py`

### Requirement: Infrastructure modules at gateway root
The following cross-cutting files SHALL remain at the `gateway/` root and SHALL NOT be moved into any subpackage: `main.py`, `config.py`, `db.py`, `schema.sql`, `Dockerfile`, `requirements.txt`, `requirements-dev.txt`, `pytest.ini`.

#### Scenario: Root files unchanged after restructure
- **WHEN** the restructure is complete
- **THEN** `gateway/main.py`, `gateway/config.py`, and `gateway/db.py` exist at the gateway root
- **THEN** no additional subdirectory named `core/`, `shared/`, or `infrastructure/` exists

### Requirement: Subpackage public interface via __init__.py
Each subpackage SHALL expose its public symbols — routers, scheduler entry-points, and key classes needed by `main.py` — through explicit named exports in its `__init__.py`. Internal helpers SHALL NOT be re-exported.

#### Scenario: main.py imports from subpackage, not from individual modules
- **WHEN** `main.py` imports a router or entry-point from a subpackage
- **THEN** the import reads `from auth import ...` or `from sync import ...`, not `from auth.hubspot_oauth import ...`

#### Scenario: __init__.py does not use wildcard imports
- **WHEN** a subpackage __init__.py is read
- **THEN** it contains explicit `from .<module> import <Name>` statements, not `from .<module> import *`

### Requirement: Test structure mirrors subpackage layout
`gateway/tests/` SHALL contain a subdirectory for each subpackage (`auth/`, `sync/`, `webhooks/`, `session/`), each containing the test modules for that subsystem. Tests that span multiple subsystems SHALL remain at the `tests/` root.

#### Scenario: Test subdirectories mirror production subpackages
- **WHEN** a developer lists `gateway/tests/`
- **THEN** subdirectories `auth/`, `sync/`, `webhooks/`, and `session/` exist, each containing the relevant `test_*.py` files

#### Scenario: Cross-subsystem tests at tests root
- **WHEN** a developer lists `gateway/tests/`
- **THEN** `test_tenant_isolation.py` and `test_credential_hygiene.py` (if present) exist at the `tests/` root, not inside a subsystem subdirectory

### Requirement: No behavioral regression from restructure
The restructure SHALL NOT change any API route, request/response contract, external dependency, or runtime behavior. All existing tests SHALL pass after each subpackage move.

#### Scenario: Health check passes after restructure
- **WHEN** `docker compose up` is run after the full restructure
- **THEN** `GET /health` returns HTTP 200

#### Scenario: All tests pass after each subpackage move
- **WHEN** `pytest` is run immediately after moving each subpackage
- **THEN** all tests pass with no new failures

### Requirement: Internal duplication may be removed without changing behavior
Real, verified code duplication SHALL be collapsible into a shared implementation at any time, provided the full existing test suite passes unchanged and no external behavior (API routes, request/response shape, tool surface) changes as a result. A cleanup pass MAY declare specific areas of the codebase explicitly out of scope, and MUST respect that boundary — no file inside a declared-excluded area is read, edited, or removed by that pass.

#### Scenario: A deduplication refactor changes no external behavior
- **WHEN** a duplicated pattern is collapsed into one shared implementation
- **THEN** the full existing test suite passes with no new failures and no test itself needed to change to accommodate the refactor

#### Scenario: An explicitly-excluded area is left untouched
- **WHEN** a cleanup pass declares a specific directory or module out of scope
- **THEN** no file under that path is modified, added, or removed by that pass

