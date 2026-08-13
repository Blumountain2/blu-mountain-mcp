## ADDED Requirements

### Requirement: Per-tenant authenticated connection to HubSpot's remote MCP endpoint
The system SHALL connect to HubSpot's remote MCP endpoint using each tenant's vaulted MCP Auth App OAuth token, established via PKCE, distinct from the Public App's token used for onboarding — confirmed live that `mcp.hubspot.com` is its own OAuth resource server and does not accept the Public App's token.

#### Scenario: Tenant pull uses only that tenant's token
- **WHEN** the system pulls data for a given hub_id
- **THEN** it authenticates using only that tenant's vaulted MCP Auth App token, never another tenant's, and never the Public App's token

### Requirement: Read-only object coverage
The system SHALL read the following object types for each authorized tenant: contacts, companies, deals, tickets, line items, products, calls, emails, meetings, notes, tasks, and the reference objects users, owners, campaigns/metrics, content, and lists. Confirmed live against the real endpoint: the core object set (contacts through tasks, plus users) has no per-object tool at all; the only way to read any of it is `query_crm_data`, one generic tool taking a SQL-like query string, against real, HubSpot-confirmed object type names (e.g. `MEETING_EVENT`, not `MEETING`). Owners/campaigns/content/lists are read via separate, generic per-object tools instead (e.g. `search_owners`), discovered dynamically rather than hardcoded. `teams`, part of the confirmed grant's stated object list, has no corresponding queryable type in the real schema at all as of this writing — a known, currently-unfilled gap in this requirement, not an oversight in the pull code.

#### Scenario: Full object set pull
- **WHEN** a pull runs for a tenant
- **THEN** data is retrieved for every in-scope object type available to that tenant's HubSpot permissions, whether via a generic per-object tool or via `query_crm_data`

### Requirement: Least-privilege scope enforcement
The system SHALL request and use only the read-only scopes needed for the in-scope object set, and SHALL NOT request any write scope. Where a query interface (`query_crm_data`) could otherwise express a write, the system SHALL additionally validate that every query sent is a single, plain read (`SELECT`) statement before sending it, independent of whatever scope-level permissions the connected token holds.

#### Scenario: No write scope requested
- **WHEN** the HubSpot Public App or MCP Auth App is configured
- **THEN** its requested/granted scopes contain only read-level permissions

#### Scenario: Non-SELECT query refused
- **WHEN** a `query_crm_data` call would send anything other than a single plain `SELECT` statement (e.g. a second statement after a semicolon, or a write-shaped keyword anywhere in the text)
- **THEN** the system refuses to send it and never calls the tool

### Requirement: Correct tenant context resolution
The system SHALL resolve the correct tenant context for every pull operation and scope all access exclusively to that tenant, regardless of whether the pull is triggered by a scheduled job or another mechanism.

#### Scenario: Tenant-scoped tool exposure
- **WHEN** a pull operation runs for a given tenant
- **THEN** only the tools and data relevant to that tenant are exposed, and no other tenant's data or errors appear in the result

### Requirement: Correct extraction of a tool call's real result
The system SHALL correctly extract a tool call's actual returned data, regardless of whether that data arrives via a declared structured-output schema or as JSON text inside a plain content block — confirmed live that none of HubSpot's real MCP tools declare an output schema, so relying on a structured-output field alone silently returns no data for every call.

#### Scenario: Tool response has no declared output schema
- **WHEN** a tool call's response carries its real payload only as JSON text in a content block, with no structured-output field populated
- **THEN** the system parses that JSON text and returns the actual data, not an empty or null result
