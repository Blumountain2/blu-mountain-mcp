## MODIFIED Requirements

### Requirement: Vertical frameworks are exactly as authored by Blu Mountain, addressable by vertical name

Each vertical framework (SaaS, PLG, Marketplace, E-commerce, Services/Project, Transactional) SHALL be addressable by vertical name and exactly as authored by Blu Mountain. It SHALL NOT be authored, rewritten, or have its analysis logic altered by this project, and SHALL NOT embed or reference any single tenant's data. The same framework content MUST be reusable, unmodified, as a runtime input for every tenant of that vertical.

For the agent hierarchy's own consumption of this content specifically, "addressable by vertical name" is satisfied by a `FRAMEWORK_TEXT` class attribute on that vertical's `gateway/frameworks/agents/verticals/*.py` class, embedded verbatim from the real source document by `gateway/scripts/embed_framework_content.py` (never hand-authored or hand-edited), rather than a database row read via `frameworks.store.get_latest()`. Content without an established code-embedding path (Challenge Library, Operating Principles, Template Library) continues to be stored and served from `analysis_content` exactly as before.

#### Scenario: Two tenants of the same vertical reference the same framework content

- **WHEN** tenant A and tenant B are both identified as "SaaS"
- **THEN** both reference the same "SaaS" framework content (their shared vertical class's `FRAMEWORK_TEXT`), and neither reference causes that content to be mutated

#### Scenario: A vertical's embedded framework text matches its real source document exactly

- **WHEN** a vertical class's `FRAMEWORK_TEXT` is compared against the real document `gateway/scripts/embed_framework_content.py` generated it from
- **THEN** the two are byte-for-byte identical

#### Scenario: An agent class cannot construct without real framework content

- **WHEN** a client agent class's vertical superclass has no `FRAMEWORK_TEXT` set (empty string)
- **THEN** construction raises a clear error immediately, rather than allowing a run to start and fail later at first use

### Requirement: The operational skill and runtime prompt are available wherever the six frameworks are, not only the six frameworks

The vertical-agnostic operational skill (`account-diagnostic-SKILL`) and the runtime invocation prompt (`Weekly_Diagnostic_Prompt`) SHALL be available to the same consumer the six vertical frameworks are, since the skill and prompt are what actually consume a framework at run time.

For the agent hierarchy's own consumption specifically, both are embedded verbatim as shared, vertical-agnostic Python constants (`OPERATIONAL_SKILL_TEXT`/`RUNTIME_PROMPT_TEXT` in `gateway/frameworks/agents/content.py`), generated the same way as the per-vertical framework text — one real skill and one real prompt, not duplicated per vertical.

#### Scenario: The operational skill is available independent of any one vertical

- **WHEN** the embedded operational skill constant is read
- **THEN** it is available without requiring any specific vertical's framework text to also be loaded, since the skill is vertical-agnostic by design

#### Scenario: The runtime prompt's placeholders survive embedding unchanged

- **WHEN** the embedded runtime prompt constant is inspected
- **THEN** it still contains the literal `{CLIENT_NAME}` and `{VERTICAL_FRAMEWORK_NAME}` placeholders, substituted only at render time, exactly as the prior database-backed version behaved
