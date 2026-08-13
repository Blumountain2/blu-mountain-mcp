## ADDED Requirements

### Requirement: HubSpot Public App install flow
The system SHALL provide an install flow that redirects a client to HubSpot's OAuth v3 authorization URL with a PKCE code challenge, and SHALL generate a cryptographically random code verifier of 43 to 128 characters using the S256 challenge method.

#### Scenario: Client starts install
- **WHEN** a client portal administrator visits the install endpoint
- **THEN** the system generates a PKCE code_verifier/code_challenge pair and redirects to HubSpot's authorization URL with the Client ID, redirect URI, requested scopes, and code_challenge

### Requirement: OAuth callback with CSRF protection
The system SHALL validate the state parameter on every callback before proceeding, and SHALL reject the callback if the state does not match what was issued during the install redirect.

#### Scenario: Valid callback
- **WHEN** HubSpot redirects back to the callback endpoint with a matching state and a valid authorization code
- **THEN** the system exchanges the code for an access/refresh token pair at the v3 token endpoint

#### Scenario: Forged or missing state
- **WHEN** the callback's state parameter does not match the one issued at install time
- **THEN** the system rejects the request and does not exchange the authorization code

### Requirement: Credentials never appear in the URL
The system SHALL send the Client ID, Client Secret, and authorization code in the POST request body when exchanging the code at HubSpot's v3 token endpoint, and SHALL NOT include these values as URL query parameters.

#### Scenario: Token exchange
- **WHEN** the system exchanges an authorization code for tokens
- **THEN** the Client ID, Client Secret, and code are transmitted only in the request body, never appended to the URL

### Requirement: App credentials and tenant tokens never conflated
The system SHALL treat the app-level Client ID and Client Secret as distinct from any tenant's issued token set, and SHALL NOT store or transmit them interchangeably.

#### Scenario: Storage separation
- **WHEN** a new tenant completes the install flow
- **THEN** the app's Client ID and Client Secret remain in environment configuration and the tenant's issued tokens are persisted separately in the token vault, keyed by hub_id

### Requirement: Standardized error handling
The system SHALL parse and surface HubSpot's standardized RFC 6749 error fields (error, error_description) returned from the v3 token endpoint.

#### Scenario: HubSpot returns an OAuth error
- **WHEN** the v3 token endpoint responds with an error field
- **THEN** the system logs the standardized error fields and returns a clear failure to the install flow without exposing credentials

### Requirement: Human-readable install outcome pages
The system SHALL present a human-readable success or error page to the browser completing the install or callback, not a raw JSON response — the actual caller of this flow is a client portal administrator's browser at the end of HubSpot's consent redirect, not a programmatic client. On success, the page SHALL show the next required step (the MCP Auth App install) and a way to continue to it.

#### Scenario: Successful Public App install
- **WHEN** the callback completes successfully
- **THEN** the browser is shown a success page identifying the connected portal and linking to the MCP Auth App install step, not a raw JSON payload

#### Scenario: Failed Public App install
- **WHEN** the callback fails for any reason (missing parameters, expired state, or a HubSpot-reported error)
- **THEN** the browser is shown an error page with a plain-language explanation and a way to retry, not a raw error code
