## MODIFIED Requirements

### Requirement: If the existing pull path omits custom properties, an explicit access mechanism is added
The system SHALL discover and pull custom properties via REST's `GET /crm/v3/properties/{objectType}` endpoint, and SHALL pass any such call through the same hand-enumerated REST endpoint allowlist as every other read path in this project.

#### Scenario: A newly-added custom-field mechanism still enforces the existing read-only allowlist
- **WHEN** a custom-field discovery or pull mechanism is used
- **THEN** every call it makes goes through the same hand-enumerated, read-only REST endpoint allowlist enforced for every other HubSpot access path in this project

#### Scenario: No new mechanism is built if the existing path already covers custom fields
- **WHEN** the default object pull already returns a portal's custom properties for a given object type
- **THEN** no additional discovery call is made for that object type beyond what's already returned

## ADDED Requirements

### Requirement: Custom-vs-standard classification uses HubSpot's own authoritative flag, not a heuristic
Wherever a property's custom/standard status is determined, the system SHALL use REST's `hubspotDefined` field from `GET /crm/v3/properties/{objectType}` rather than the `is_custom_property_name()` heuristic used under the prior MCP-based mechanism.

#### Scenario: A property's classification matches HubSpot's own record
- **WHEN** a property's custom/standard status is reported anywhere in this project (profiling output, agent context, etc.)
- **THEN** that classification matches HubSpot's own `hubspotDefined` value for that property, not a hand-curated guess
