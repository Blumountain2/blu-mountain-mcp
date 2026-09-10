## MODIFIED Requirements

### Requirement: Gateway subpackage structure
The gateway service SHALL organize production domain modules into five functional subpackages within `gateway/`: `auth/`, `sync/`, `webhooks/`, `session/`, and `frameworks/`. Each subpackage SHALL contain only the modules belonging to its subsystem.

The fourth subpackage is named `session/`, not `mcp/`: this project depends on `fastmcp`, which itself depends on the official `mcp` PyPI SDK (imported internally as `mcp.types` etc). A local subpackage literally named `mcp` shadows that dependency on `sys.path` and breaks `fastmcp`'s own imports.

The fifth subpackage, `frameworks/`, is the analysis-content and vertical/client-agent subsystem (`openspec/changes/analysis-model-templates/`, `openspec/changes/client-vertical-agent-classes/`) — it predates this requirement's own formal documentation of it as a subpackage, having grown alongside the other four without previously being named here.

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

#### Scenario: frameworks subpackage contains the analysis-content and agent modules
- **WHEN** a developer lists files in `gateway/frameworks/`
- **THEN** it contains `store.py`, `ingest.py`, `_versioning.py`, `guidance.py`, `vertical.py`, `profiling.py`, `pull_agent.py`, plus an `__init__.py`, and a nested `agents/` subpackage (see the separate agent-hierarchy requirements below)

### Requirement: Infrastructure modules at gateway root
The following cross-cutting files SHALL remain at the `gateway/` root and SHALL NOT be moved into any subpackage: `main.py`, `config.py`, `db.py`, `debug_api.py`, `schema.sql`, `Dockerfile`, `requirements.txt`, `requirements-dev.txt`, `pytest.ini`.

`debug_api.py` stays at the root rather than inside `sync/` or `auth/` because it is a cross-cutting HTTP surface spanning both (HubSpot pulls and the token vault) plus its own gating, the same "spans more than one subsystem, imported directly by `main.py`" rationale that already keeps `main.py`, `config.py`, and `db.py` at the root instead of inside a subpackage.

#### Scenario: Root files unchanged after restructure
- **WHEN** the restructure is complete
- **THEN** `gateway/main.py`, `gateway/config.py`, `gateway/db.py`, and `gateway/debug_api.py` exist at the gateway root
- **THEN** no additional subdirectory named `core/`, `shared/`, or `infrastructure/` exists

### Requirement: Test structure mirrors subpackage layout
`gateway/tests/` SHALL contain a subdirectory for each subpackage (`auth/`, `sync/`, `webhooks/`, `session/`, `frameworks/`), each containing the test modules for that subsystem. `gateway/tests/frameworks/` SHALL itself contain a nested `agents/` subdirectory mirroring `gateway/frameworks/agents/`. Tests that span multiple subsystems SHALL remain at the `tests/` root.

#### Scenario: Test subdirectories mirror production subpackages
- **WHEN** a developer lists `gateway/tests/`
- **THEN** subdirectories `auth/`, `sync/`, `webhooks/`, `session/`, and `frameworks/` exist, each containing the relevant `test_*.py` files, and `gateway/tests/frameworks/agents/` exists mirroring `gateway/frameworks/agents/`

#### Scenario: Cross-subsystem tests at tests root
- **WHEN** a developer lists `gateway/tests/`
- **THEN** `test_tenant_isolation.py` and `test_credential_hygiene.py` (if present) exist at the `tests/` root, not inside a subsystem subdirectory

## ADDED Requirements

### Requirement: The agent hierarchy's tool schemas and dispatch live in their own module
`gateway/frameworks/agents/` SHALL keep the tool-calling loop mechanics (`BaseAgent` itself: the loop, prompt assembly, run orchestration) in `base.py`, separate from the tool schemas and tool-dispatch logic that loop executes, which SHALL live in `tools.py`. `base.py` SHALL import from `tools.py` rather than defining tool schemas or dispatch logic inline.

#### Scenario: Tool schemas and dispatch are not defined in base.py
- **WHEN** a developer lists the contents of `gateway/frameworks/agents/base.py`
- **THEN** it contains the agent run loop and prompt assembly, but no tool schema list or tool-dispatch function body

#### Scenario: A developer looking for tool definitions finds them in one place
- **WHEN** a developer lists the contents of `gateway/frameworks/agents/tools.py`
- **THEN** it contains the tool schema definitions and the dispatch logic that executes them

### Requirement: The agent hierarchy's directory structure is explicit
`gateway/frameworks/agents/` SHALL contain: `base.py` (loop mechanics), `tools.py` (tool schemas and dispatch), `registry.py` (hub_id to client class lookup), `verticals/` (one file per vertical subclass), and `clients/` (one file per client subclass), each subdirectory with its own `__init__.py`.

#### Scenario: The agent directory matches the specified layout
- **WHEN** a developer lists `gateway/frameworks/agents/`
- **THEN** `base.py`, `tools.py`, `registry.py`, `verticals/`, and `clients/` are all present, each subdirectory containing an `__init__.py`
