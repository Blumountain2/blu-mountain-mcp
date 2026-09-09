# analysis-template-schema Specification

## Purpose
Storing and serving Blu Mountain's own authored vertical frameworks, operational skill, and runtime prompt exactly as delivered — this project ingests and serves that content, it never authors, forks, or tenant-scopes it.
## Requirements
### Requirement: Vertical frameworks are stored as delivered, independent of any tenant
Each vertical framework (SaaS, PLG, Marketplace, E-commerce, Services/Project, Transactional) SHALL be stored as its own versioned entity, addressable by vertical name, exactly as authored by Blu Mountain. It SHALL NOT be authored, rewritten, or have its analysis logic altered by this project, and SHALL NOT embed or reference any single tenant's data. The same stored framework MUST be reusable, unmodified, as a runtime input for every tenant of that vertical.

#### Scenario: Two tenants of the same vertical reference the same stored framework
- **WHEN** tenant A and tenant B are both identified as "SaaS"
- **THEN** both reference the same stored "SaaS" framework content, and neither reference causes that stored content to be mutated

### Requirement: Stored content includes the operational skill and runtime prompt, not only the six frameworks
The stored content SHALL include `account-diagnostic-SKILL` (the vertical-agnostic operational skill) and `Weekly_Diagnostic_Prompt` (the runtime invocation prompt), in addition to the six vertical frameworks, since the skill and prompt are what actually consume a framework at run time.

#### Scenario: The operational skill is retrievable independent of any one vertical
- **WHEN** the stored operational skill is read
- **THEN** it is returned without requiring a specific vertical framework to also be loaded, since the skill is vertical-agnostic by design

### Requirement: Stored content is Claude-facing instruction text, not a trained model artifact
All stored content SHALL consist of instruction text intended for a Claude prompt/agent configuration (frameworks, the operational skill, the runtime prompt). It SHALL NOT reference, require, or depend on any machine-learning training artifact, model weights, or model-hosting infrastructure.

#### Scenario: Stored framework content is plain instruction text
- **WHEN** a vertical framework is loaded from storage
- **THEN** its content is structured instruction/reference text, not a binary model artifact or a reference to one

### Requirement: Stored content also includes Blu Mountain's remaining delivered reference material
In addition to the six vertical frameworks, the operational skill, and the runtime prompt, the stored content SHALL include the six per-vertical Challenge Library documents, `Blu_Operating_Principles.md`, and the Template Library (`BluMountain_Template_Library_v1_3`), each stored and versioned independently, exactly as delivered. These SHALL NOT be treated as, or reformatted into, operational skill bodies unless a future decision explicitly changes that (see `design.md`'s Open Questions) — they are stored and served as reference content in their delivered form.

#### Scenario: A vertical's Challenge Library is retrievable independent of that vertical's framework
- **WHEN** the stored "SaaS" Challenge Library document is read
- **THEN** it is returned without requiring the "SaaS" vertical framework to also be loaded, and its content is unmodified from what Blu Mountain delivered

#### Scenario: Operating principles and the template library are addressable independently of any vertical
- **WHEN** `Blu_Operating_Principles.md` or the Template Library is read from storage
- **THEN** it is retrievable on its own, not only as a byproduct of loading a specific vertical framework

### Requirement: Framework content versions independently of any tenant-specific record
Updating a stored framework, skill, or prompt to a new version SHALL NOT modify or invalidate any tenant-specific artifact already produced against an earlier version (e.g. a client's own `CONFIRMED_FIELDS`, git-committed against a framework version at the time it was curated).

#### Scenario: A framework update does not affect an already-curated client field list
- **WHEN** the stored "SaaS" framework is updated to a new version
- **THEN** a client's `CONFIRMED_FIELDS`, already curated against the prior version, continues to read as it did before the update — updating the framework never rewrites or invalidates it

