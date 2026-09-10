## ADDED Requirements

### Requirement: A tenant's vertical is visible through the live session without reading code
The live session's tenant-listing tool SHALL include each permitted tenant's vertical assignment in its response, resolved from the existing client agent registry rather than requiring a developer to read `gateway/frameworks/agents/clients/` source directly.

#### Scenario: The tenant list includes each tenant's vertical
- **WHEN** a staff member calls the tenant-listing tool
- **THEN** each returned tenant includes its vertical assignment alongside its `hub_id` and name

### Requirement: A tenant with no registered client agent class still lists successfully
A permitted tenant with no class currently registered in the agent registry SHALL still appear in the tenant-listing response, with its vertical field indicating that no assignment exists yet, rather than the whole call failing.

#### Scenario: An unregistered tenant does not break the listing
- **WHEN** the tenant-listing tool is called and one permitted tenant has no registered client agent class
- **THEN** that tenant still appears in the response, with an explicit indication that its vertical is not yet assigned, and every other tenant's data is unaffected

### Requirement: Vertical visibility reads only the existing registry, never a new store
Resolving a tenant's vertical for this purpose SHALL read only the existing in-code client agent registry (`registry.get_registered_agent_class`/`registry.registered_hub_ids`). It SHALL NOT introduce a new persisted store, cache, or database column duplicating what the registry already holds.

#### Scenario: No new persistence layer is introduced for this purpose
- **WHEN** this capability is implemented
- **THEN** no new database table or column stores a tenant's vertical independently of the registry
