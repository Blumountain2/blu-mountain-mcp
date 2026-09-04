## ADDED Requirements

### Requirement: One shared base class holds only the loop mechanics
A single base agent class SHALL implement the tool-calling loop, tool dispatch, the bounded tool-call safety cap, hub_id-scoped HubSpot client construction, and run audit logging. This class SHALL contain no vertical-specific or client-specific business content (no framework text, no field lists).

#### Scenario: The base class alone cannot run for any real vertical
- **WHEN** the base agent class is inspected
- **THEN** it declares no vertical-specific prompt content and no client-specific field list — those are required attributes a subclass must supply

### Requirement: Each vertical is its own subclass
Each of the six business verticals SHALL have its own class, in its own file, declaring that vertical's system-prompt additions as real code rather than a database row.

#### Scenario: A vertical's agent class can be reviewed and edited independently
- **WHEN** a vertical's system-prompt additions need to change
- **THEN** only that vertical's own file is edited; no other vertical's file or the base class changes

### Requirement: Each client is its own subclass of its vertical
Each client with a real agent SHALL have its own class, subclassing its vertical's class, declaring its own hub_id and which HubSpot fields (standard object properties or custom-object properties) its agent looks at.

#### Scenario: A client's confirmed fields narrow what is pulled
- **WHEN** a client's class declares confirmed fields for a given object type
- **THEN** the agent requests exactly those fields from HubSpot for that object type, not the full discovered set

#### Scenario: A client with no confirmed fields for an object type still works
- **WHEN** a client's class declares no confirmed fields for a given object type
- **THEN** the agent falls back to full live discovery for that object type, unchanged from today's behavior

#### Scenario: Two clients of the same vertical are genuinely independent code
- **WHEN** one client's file is edited
- **THEN** no other client's file changes, even if both subclass the same vertical

### Requirement: An unknown tenant is refused clearly, never silently defaulted
Running the agent for a hub_id with no registered client class SHALL raise a clear error identifying the missing registration, never silently fall back to a generic or default agent.

#### Scenario: A tenant with no authored client class cannot run
- **WHEN** `run_client_agent` is called for a hub_id with no registered class
- **THEN** it raises an error naming that hub_id, rather than running any other client's or vertical's configuration on its behalf

### Requirement: The agent can discover and pull a client's own custom objects
The base agent class SHALL expose tools to discover a tenant's real custom object schemas and pull one by its discovered object type identifier, using the same read-only, hub_id-scoped pull path every other tool uses. This SHALL be available to every vertical and every client uniformly, since a tenant's custom objects are runtime-discovered data no class can hardcode ahead of time.

#### Scenario: A client's real custom object is reachable through the agent
- **WHEN** a client's portal has a real custom object
- **THEN** the agent can discover and pull it through its own tool loop, regardless of which vertical or client class is running

### Requirement: Isolation holds across the class hierarchy
No agent run SHALL be able to read or act on any tenant's HubSpot data other than the one hub_id its class (or the calling wrapper) was constructed for, regardless of which vertical or client class is involved.

#### Scenario: One client's run never uses another client's token
- **WHEN** an agent runs for client A
- **THEN** every HubSpot call in that run uses only client A's own vaulted token, never client B's, even if both share the same vertical class
