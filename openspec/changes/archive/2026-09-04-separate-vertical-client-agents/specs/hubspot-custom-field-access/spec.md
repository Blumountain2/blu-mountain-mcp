## ADDED Requirements

### Requirement: Custom property coverage of the existing pull path is confirmed live, not assumed
Before any new pull-path code is built for custom fields, the system SHALL confirm, against a real HubSpot test portal with at least one known custom property, whether `HubSpotDataPullClient.pull_crm_objects()`'s existing query already returns that property.

#### Scenario: Confirmation happens before new code is written
- **WHEN** this capability is implemented
- **THEN** a live test against a real portal with a known custom property records whether the existing pull already returns it, and that result gates which of the requirements below applies

### Requirement: Custom properties are distinguishable from standard properties in profiling output
Wherever a tenant's populated HubSpot fields are profiled (`tenant-field-profiling`), the system SHALL indicate which of those fields are custom (non-standard, portal-specific) properties versus HubSpot's own standard properties.

#### Scenario: A custom field is identifiable in a tenant's profile
- **WHEN** a tenant's fields are profiled and at least one populated field is a custom property
- **THEN** that field is identifiable as custom in the profiling output, distinct from standard properties

### Requirement: If the existing pull path omits custom properties, an explicit access mechanism is added
If live confirmation shows the existing pull path does not return a portal's custom properties, the system SHALL add a mechanism to explicitly discover and pull them, reusing HubSpot's own MCP surface if it already exposes a schema/properties-listing tool, and SHALL pass any new mechanism through the same `_is_read_safe`/`_is_safe_select` checks as every other read path.

#### Scenario: A newly-added custom-field mechanism still enforces the existing read-only allowlist
- **WHEN** a custom-field discovery or pull mechanism is added
- **THEN** every call it makes is checked by the same read-safety logic already enforced for every other HubSpot access path in this project

#### Scenario: No new mechanism is built if the existing path already covers custom fields
- **WHEN** live confirmation shows the existing pull path already returns custom properties
- **THEN** no new HubSpot access path is added, and the remaining work is scoped to the profiling-output distinction above only
