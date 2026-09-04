# hubspot-custom-field-access Specification

## Purpose
Reaching a tenant's custom (portal-specific) HubSpot properties, not just HubSpot's own standard fields, and correctly distinguishing the two — both in what gets pulled and in how profiling reports on it.
## Requirements
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
The system SHALL discover and pull custom properties via REST's `GET /crm/v3/properties/{objectType}` endpoint, and SHALL pass any such call through the same hand-enumerated REST endpoint allowlist as every other read path in this project.

#### Scenario: A newly-added custom-field mechanism still enforces the existing read-only allowlist
- **WHEN** a custom-field discovery or pull mechanism is used
- **THEN** every call it makes goes through the same hand-enumerated, read-only REST endpoint allowlist enforced for every other HubSpot access path in this project

#### Scenario: No new mechanism is built if the existing path already covers custom fields
- **WHEN** the default object pull already returns a portal's custom properties for a given object type
- **THEN** no additional discovery call is made for that object type beyond what's already returned

### Requirement: Custom-vs-standard classification uses HubSpot's own authoritative flag, not a heuristic
Wherever a property's custom/standard status is determined, the system SHALL use REST's `hubspotDefined` field from `GET /crm/v3/properties/{objectType}` rather than the `is_custom_property_name()` heuristic used under the prior MCP-based mechanism.

#### Scenario: A property's classification matches HubSpot's own record
- **WHEN** a property's custom/standard status is reported anywhere in this project (profiling output, agent context, etc.)
- **THEN** that classification matches HubSpot's own `hubspotDefined` value for that property, not a hand-curated guess

