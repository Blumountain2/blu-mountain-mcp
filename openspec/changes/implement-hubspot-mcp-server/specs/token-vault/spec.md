## ADDED Requirements

### Requirement: Per-tenant token persistence
The system SHALL persist each tenant's issued access and refresh token pair in Postgres, keyed by hub_id, upon successful install. This applies identically to both vaulted HubSpot credentials this system holds per tenant — the Public App's token (`tokens`) and the MCP Auth App's token (`mcp_tokens`, spec Section 4.1, a separate credential required because `mcp.hubspot.com` does not accept the Public App's token) — via the same parameterized vault implementation rather than duplicated logic per credential.

#### Scenario: Successful install persists tokens
- **WHEN** a tenant completes the OAuth install flow
- **THEN** the system stores the encrypted access token, encrypted refresh token, and expiry in a tokens table keyed by that tenant's hub_id

#### Scenario: Second credential requires the first to already exist
- **WHEN** the MCP Auth App install runs for a portal that has not yet completed the Public App install
- **THEN** the system rejects it with a clear, actionable error rather than persisting a token row with no corresponding tenant

### Requirement: Per-tenant derived encryption keys
The system SHALL encrypt every tenant's stored tokens with AES-256 using a key derived from a single root key via HKDF, using the tenant's hub_id as derivation context, such that no tenant's key is derivable from another tenant's data.

#### Scenario: Cross-tenant key isolation
- **WHEN** tenant A's encrypted token is decrypted using tenant B's derived key
- **THEN** decryption fails

#### Scenario: Plain-text storage prohibited
- **WHEN** a token is persisted
- **THEN** it is never written to storage in plain text form

### Requirement: Access-token cache with bounded TTL
The system SHALL cache access tokens through a cache interface with a time-to-live equal to the token's expiry, and SHALL NOT place refresh tokens in this cache.

#### Scenario: Cache respects expiry
- **WHEN** an access token is cached
- **THEN** it expires from the cache no later than the token's own expiry

#### Scenario: Refresh token excluded from cache
- **WHEN** a token pair is issued
- **THEN** the refresh token is stored only in the persistent encrypted vault, never in the cache

### Requirement: Proactive token refresh
The system SHALL refresh a tenant's access token when the current time is within five minutes of its expiry, rather than waiting for a failed request.

#### Scenario: Refresh triggered ahead of expiry
- **WHEN** a tenant's access token has less than five minutes remaining before expiry
- **THEN** the system refreshes it using the stored refresh token before it is used again

### Requirement: Serialized concurrent refresh
The system SHALL serialize token refresh per tenant using Postgres advisory locks, such that two concurrent instances never refresh the same tenant's token simultaneously.

#### Scenario: Concurrent refresh attempts
- **WHEN** two service instances attempt to refresh the same tenant's token at the same time
- **THEN** only one refresh proceeds and the other waits or no-ops without double-refreshing

### Requirement: No token passthrough to external consumers
The system SHALL NOT expose a tenant's raw HubSpot access token or refresh token to any external consumer, including Airtable writes, staff-facing endpoints, and audit log entries. Only the vault and the components that directly use a token to call HubSpot may hold it in memory.

#### Scenario: Token excluded from Airtable writes
- **WHEN** normalized HubSpot data is written to Airtable
- **THEN** the record contains no raw access token or refresh token value

#### Scenario: Token excluded from audit log entries
- **WHEN** an audit log entry is recorded for a token refresh or a pull
- **THEN** the entry references the event and the tenant, never the raw token value

### Requirement: HubSpot uninstall webhook
The system SHALL receive HubSpot's app-lifecycle webhook, validate its HMAC SHA-256 signature, reject any request older than five minutes, and invalidate the tenant's stored token set on a valid uninstall event.

#### Scenario: Valid uninstall event
- **WHEN** a correctly signed, recent uninstall webhook is received for a tenant
- **THEN** that tenant's stored token set is invalidated and re-authorization is supported

#### Scenario: Unsigned or stale webhook rejected
- **WHEN** a webhook request has an invalid signature or is older than five minutes
- **THEN** the system rejects it and does not modify any tenant's token state
