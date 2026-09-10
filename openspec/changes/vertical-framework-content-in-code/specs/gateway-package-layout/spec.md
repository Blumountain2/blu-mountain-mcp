## MODIFIED Requirements

### Requirement: The agent hierarchy's directory structure is explicit

`gateway/frameworks/agents/` SHALL contain: `base.py` (loop mechanics), `tools.py` (tool schemas and dispatch), `diagnostics.py` (the diagnostic phase), `content.py` (shared, embedded operational-skill/runtime-prompt constants), `registry.py` (hub_id to client class lookup), `verticals/` (one file per vertical subclass, each embedding that vertical's own real framework text), and `clients/` (one file per client subclass), each subdirectory with its own `__init__.py`.

#### Scenario: The agent directory matches the specified layout

- **WHEN** a developer lists `gateway/frameworks/agents/`
- **THEN** `base.py`, `tools.py`, `diagnostics.py`, `content.py`, `registry.py`, `verticals/`, and `clients/` are all present, each subdirectory containing an `__init__.py`

## ADDED Requirements

### Requirement: A maintenance script regenerates embedded framework/skill/prompt content

`gateway/scripts/` SHALL contain `embed_framework_content.py`, the maintenance script that regenerates `gateway/frameworks/agents/verticals/*.py`'s `FRAMEWORK_TEXT` attributes and `gateway/frameworks/agents/content.py`'s constants from Blu Mountain's real source documents, alongside `frameworks/ingest.py` (the equivalent script for content still served from `analysis_content`).

#### Scenario: The embedding script exists alongside the ingestion script

- **WHEN** a developer lists `gateway/scripts/`
- **THEN** `embed_framework_content.py` is present, callable the same way `frameworks/ingest.py`'s CLI is (a `--source-dir` pointing at the delivered documentation directory)
