## ADDED Requirements

### Requirement: Each vertical has its own persisted, independently-versioned agent template
The system SHALL persist exactly one current agent template per vertical, storing that vertical's system-prompt additions (beyond the raw framework text already stored in `analysis_content`) and its tool/model configuration, versioned so an update to one vertical's template never alters another vertical's template or any already-produced client agent instance built from an earlier version.

#### Scenario: Updating one vertical's template doesn't affect another vertical
- **WHEN** a new version of the SaaS vertical's agent template is created
- **THEN** the PLG vertical's current template is unchanged, and every other vertical's template remains at its own independent version

#### Scenario: A prior version stays retrievable after a new one is created
- **WHEN** a vertical's agent template is updated to a new version
- **THEN** the prior version remains stored and retrievable by version, and any client agent instance already built from it keeps referencing that specific version

### Requirement: A vertical agent template never contains client-specific data
A vertical agent template SHALL contain only vertical-level configuration shared across every client of that vertical, and SHALL NOT reference or embed any single client's identity, fields, or data.

#### Scenario: A vertical template has no client references
- **WHEN** a vertical agent template is created or updated
- **THEN** nothing in its stored content identifies, or is scoped to, any individual client

### Requirement: A vertical agent template is retrievable by vertical and version
The system SHALL provide a way to retrieve a vertical's current (latest) agent template, and any specific prior version by number, mirroring the retrieval pattern already proven for `analysis_content`.

#### Scenario: The current template is retrievable by vertical name
- **WHEN** the current agent template for a known vertical is requested
- **THEN** the latest version's system-prompt additions and tool/model configuration are returned

#### Scenario: A specific prior version is retrievable independent of the current one
- **WHEN** a specific version number of a vertical's agent template is requested
- **THEN** that exact version's content is returned, regardless of what the current latest version is
