## ADDED Requirements

### Requirement: FastMCP OAuth Proxy fronts the live session
The system SHALL expose the live interactive session as a remote MCP server whose authorization layer is FastMCP's OAuth Proxy, presenting a Dynamic Client Registration-compliant, Protected Resource Metadata-serving interface to connecting MCP clients (Claude Desktop, Claude Code, or Claude Cowork — identically to any of the three), while using exactly one manually pre-registered Google Workspace OAuth client as the upstream credential.

#### Scenario: MCP client discovers the session like any other remote MCP server
- **WHEN** an MCP client requests Protected Resource Metadata from the live session's endpoint
- **THEN** the system responds with a DCR-compliant metadata document, without requiring the client to be manually pre-registered

### Requirement: No upstream token passthrough
The system SHALL issue its own audience-scoped JWT to the connecting MCP client upon successful Google Workspace sign-in, and SHALL NOT forward Google's own access or ID token to that client.

#### Scenario: Client receives a proxy-issued token
- **WHEN** a staff member completes Google Workspace sign-in through the OAuth Proxy
- **THEN** the connecting MCP client receives a JWT issued by the OAuth Proxy itself, scoped to this resource server's audience, never Google's raw token

### Requirement: Google Workspace domain allowlist enforcement
The system SHALL reject any sign-in attempt whose Google Workspace domain claim falls outside the configured allowlist, on every login, not only at initial registration.

#### Scenario: Allowed domain signs in
- **WHEN** a staff member signs in with an account on an allowlisted Workspace domain
- **THEN** the sign-in proceeds and a session is established

#### Scenario: Disallowed domain rejected
- **WHEN** a sign-in attempt presents a Google Workspace domain claim not on the allowlist
- **THEN** the system rejects the sign-in and no session is established

#### Scenario: Unconfigured allowlist fails closed
- **WHEN** the allowlist is empty or unconfigured
- **THEN** the system rejects every sign-in attempt rather than admitting every domain, since this check is the sole gate on tenant access under the default-open model below

### Requirement: Default-open tenant access, explicitly restrictable
The system SHALL grant any staff member who signs in successfully access to every installed tenant by default, and SHALL maintain a Postgres deny-list mapping specific staff identities to specific tenants they are explicitly restricted from; the system SHALL NOT serve HubSpot data for any tenant a staff member is restricted from, and SHALL NOT require an explicit grant for any tenant they are not restricted from.

#### Scenario: Default access with no restriction
- **WHEN** a staff member with no restriction rows queries HubSpot data for any installed tenant
- **THEN** the system serves the data, with no prior grant having been made

#### Scenario: Restricted tenant query rejected
- **WHEN** a staff member queries HubSpot data for a tenant they are explicitly restricted from
- **THEN** the system rejects the request and serves no data for that tenant

#### Scenario: Uninstalled tenant excluded from default access
- **WHEN** a tenant's install status is not `installed` (e.g. uninstalled)
- **THEN** no staff member is granted default access to it, restricted or not

### Requirement: Explicit tenant selection for multi-tenant staff
The system SHALL require a staff member permitted to access more than one tenant to explicitly select exactly one tenant before any HubSpot data is returned in that session.

#### Scenario: Multi-tenant staff member has not yet selected a tenant
- **WHEN** a staff member permitted to access more than one tenant issues a data query before selecting a tenant
- **THEN** the system prompts for tenant selection and returns no HubSpot data

#### Scenario: Multi-tenant staff member has selected a tenant
- **WHEN** a staff member with more than one permitted tenant has explicitly selected one for the session
- **THEN** subsequent queries in that session are scoped to the selected tenant only

### Requirement: Per-access audit logging by staff identity and tenant
The system SHALL record an audit log entry for every interactive HubSpot data access made through the live session, attributing it to the specific staff identity and tenant involved, and SHALL also record every denied attempt — a rejected sign-in, a rejected tenant selection, or a staff member with no permitted tenant — not only successful access, since a denied attempt against a confidentiality boundary is exactly the kind of event this audit log exists to attribute to a person.

#### Scenario: Interactive access is audited
- **WHEN** a staff member's session returns HubSpot data for a tenant
- **THEN** an audit log entry is recorded identifying the staff member, the tenant, and the access, in the same Postgres audit log used elsewhere in the system

#### Scenario: Denied access is audited
- **WHEN** a staff member is denied access to a specific tenant, denied sign-in by the domain allowlist, or has no permitted tenant at all
- **THEN** an audit log entry is recorded for that denial with the same attribution as a successful access, not silently dropped

### Requirement: Shared data-pull layer, no duplicate HubSpot client
The system SHALL serve live session queries through the same per-tenant `hubspot-data-pull` client and vaulted-token access used by the scheduled staging job, rather than a separate HubSpot client implementation.

#### Scenario: Live session query reuses the vaulted token path
- **WHEN** the live session queries HubSpot data for the selected tenant
- **THEN** the query is served through the existing token-vault-backed pull client, subject to the same least-privilege scopes and rate limiting as the scheduled job
