## ADDED Requirements

### Requirement: Internal duplication may be removed without changing behavior
Real, verified code duplication SHALL be collapsible into a shared implementation at any time, provided the full existing test suite passes unchanged and no external behavior (API routes, request/response shape, tool surface) changes as a result. A cleanup pass MAY declare specific areas of the codebase explicitly out of scope, and MUST respect that boundary — no file inside a declared-excluded area is read, edited, or removed by that pass.

#### Scenario: A deduplication refactor changes no external behavior
- **WHEN** a duplicated pattern is collapsed into one shared implementation
- **THEN** the full existing test suite passes with no new failures and no test itself needed to change to accommodate the refactor

#### Scenario: An explicitly-excluded area is left untouched
- **WHEN** a cleanup pass declares a specific directory or module out of scope
- **THEN** no file under that path is modified, added, or removed by that pass
