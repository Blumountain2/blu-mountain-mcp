## ADDED Requirements

### Requirement: MCP Auth App install flow, separate from the Public App
The system SHALL provide a second install flow, distinct from the Public App's, that redirects a client to `mcp.hubspot.com`'s own OAuth authorization URL with a PKCE code challenge — confirmed live that `mcp.hubspot.com` is its own OAuth resource server (its own RFC 9728/8414 metadata) and does not accept the Public App's CRM-scoped token.

#### Scenario: Client starts the MCP Auth App install
- **WHEN** a client portal administrator visits the MCP Auth App install endpoint
- **THEN** the system generates a PKCE code_verifier/code_challenge pair and redirects to `mcp.hubspot.com`'s own authorization URL with the MCP Auth App's Client ID, redirect URI, and code_challenge

### Requirement: MCP Auth App install requires the Public App install to already exist for that portal
The system SHALL reject an MCP Auth App callback for a portal that has not already completed the Public App install, with a clear, actionable error rather than a raw database error.

#### Scenario: MCP Auth App install attempted out of order
- **WHEN** the MCP Auth App callback completes token exchange for a hub_id with no existing tenant row
- **THEN** the system rejects it with an error identifying the missing prerequisite, and does not persist a token row

### Requirement: OAuth callback with CSRF protection
The system SHALL validate the state parameter on every MCP Auth App callback before proceeding, using the same single-use, time-bounded state mechanism as the Public App's install flow.

#### Scenario: Valid callback
- **WHEN** `mcp.hubspot.com` redirects back to the callback endpoint with a matching state and a valid authorization code
- **THEN** the system exchanges the code for an access/refresh token pair and persists it into a vault separate from the Public App's

#### Scenario: Forged or missing state
- **WHEN** the callback's state parameter does not match the one issued at install time, or is missing
- **THEN** the system rejects the request and does not exchange the authorization code

### Requirement: Portal identifier resolved from the token exchange response directly
The system SHALL resolve the portal identifier (hub_id) for the MCP Auth App's token from the token exchange response body itself, not from a separate introspection call — confirmed live that `mcp.hubspot.com`'s introspection endpoint returns only RFC 7662's minimal `{"active": true/false}`, with no portal identifier at all, so it is not a viable source.

#### Scenario: hub_id present in token response
- **WHEN** the MCP Auth App's token endpoint returns a successful token exchange response
- **THEN** the system reads the portal identifier from a recognized field on that same response body

### Requirement: Credentials never appear in the URL
The system SHALL send the MCP Auth App's Client ID, Client Secret, and authorization code in the POST request body when exchanging the code, and SHALL NOT include these values as URL query parameters.

#### Scenario: Token exchange
- **WHEN** the system exchanges an authorization code for MCP Auth App tokens
- **THEN** the Client ID, Client Secret, and code are transmitted only in the request body, never appended to the URL

### Requirement: Vaulted separately from the Public App's token
The system SHALL store the MCP Auth App's token pair in a distinct table from the Public App's token, keyed by the same hub_id, with the same encryption and proactive-refresh guarantees as the Public App's vault.

#### Scenario: Independent refresh lifecycle
- **WHEN** the MCP Auth App's access token is refreshed
- **THEN** only the MCP Auth App's vaulted row is updated; the Public App's token and expiry are unaffected

### Requirement: Human-readable install outcome pages
The system SHALL present a human-readable success or error page to the browser completing an MCP Auth App install or callback, not a raw JSON response — the actual caller of this flow is a portal administrator's browser at the end of a consent redirect, not a programmatic client. On success, when a further step exists, the page SHALL show that step's URL and a way to continue to it.

#### Scenario: Successful MCP Auth App install
- **WHEN** the MCP Auth App callback completes successfully
- **THEN** the browser is shown a success page identifying the connected portal, not a raw JSON payload

#### Scenario: Failed MCP Auth App install
- **WHEN** the MCP Auth App callback fails for any reason (missing parameters, expired state, a HubSpot-reported error, or a missing Public App install)
- **THEN** the browser is shown an error page with a plain-language explanation and a way to retry, not a raw error code
