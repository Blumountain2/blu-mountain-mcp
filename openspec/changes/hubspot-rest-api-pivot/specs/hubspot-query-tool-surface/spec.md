## MODIFIED Requirements

### Requirement: A category tool can be scoped to a client's confirmed-relevant or custom fields
Each category-scoped query tool SHALL accept an optional property-selection parameter, and SHALL be able to reference the calling client's own confirmed-relevant fields (from its onboarding profile) when deciding what's selectable. Under the REST-based pull path, an explicit property list SHALL narrow the response to exactly those properties, not additively alongside HubSpot's own default set — a real behavior change from the prior MCP-based mechanism, confirmed live during implementation rather than assumed to carry over unchanged.

#### Scenario: A property-selection parameter returns exactly the requested properties
- **WHEN** a category tool is called with an explicit property list
- **THEN** only those properties are returned for the requested records — not HubSpot's default set in addition to them

#### Scenario: An unscoped call still returns a sensible default
- **WHEN** a category tool is called with no property-selection parameter
- **THEN** it returns HubSpot's own default field set for that object type, so existing callers see no regression
