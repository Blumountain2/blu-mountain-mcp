## ADDED Requirements

### Requirement: HubSpot data-query tools are grouped by category, not one generic tool or one tool per object type
The live session SHALL expose HubSpot CRM data through a small number of category-scoped tools (CRM Records, Engagement Records, Marketing/Content, Users) rather than a single generic `query_hubspot_data` tool or one tool per individual HubSpot object type.

#### Scenario: A category tool only returns its own category's object types
- **WHEN** the CRM Records tool is called with a specific object type
- **THEN** it returns data only for object types within its own category, and a request for an out-of-category object type is rejected rather than silently handled

#### Scenario: Every previously-reachable object type remains reachable
- **WHEN** the category-scoped tools replace the single generic tool
- **THEN** every object type the generic tool could reach before is still reachable through exactly one of the new category tools

### Requirement: A category tool can be scoped to a client's confirmed-relevant or custom fields
Each category-scoped query tool SHALL accept an optional property-selection parameter, and SHALL be able to reference the calling client's own confirmed-relevant fields (from its onboarding profile) when deciding what's selectable.

#### Scenario: A property-selection parameter narrows the returned fields
- **WHEN** a category tool is called with an explicit property list
- **THEN** only those properties are returned for the requested records, alongside whatever baseline fields the tool always includes

#### Scenario: An unscoped call still returns a sensible default
- **WHEN** a category tool is called with no property-selection parameter
- **THEN** it returns the same baseline field set the current generic tool already returns, so existing callers see no regression

### Requirement: Existing MCP prompts are updated to reference the new tool names
The `tenant_pipeline_overview` and `tenant_recent_activity` prompts SHALL reference the new category-scoped tool names and appropriate object types, rather than the retired single `query_hubspot_data` tool.

#### Scenario: A prompt's guidance names a real, current tool
- **WHEN** either existing MCP prompt is rendered
- **THEN** every tool name it references matches one of the current category-scoped tools
