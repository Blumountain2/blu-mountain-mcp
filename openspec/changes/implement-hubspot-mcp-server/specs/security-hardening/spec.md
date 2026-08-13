## ADDED Requirements

### Requirement: Per-tenant rate limiting
The system SHALL enforce a per-tenant token-bucket rate limit using Postgres, such that one tenant's request volume cannot degrade service for another tenant.

#### Scenario: Rate limit exceeded
- **WHEN** a tenant exceeds its allotted requests within the configured window
- **THEN** further requests for that tenant are rejected or delayed without affecting other tenants

### Requirement: Persistent per-tenant audit log
The system SHALL record every pull, credential access, and outcome in a per-tenant audit log retained for a minimum of 60 days, including who, what, when, and which client.

#### Scenario: Audit entry recorded
- **WHEN** any tool call, pull, or credential access occurs
- **THEN** an audit log entry is recorded with sufficient detail to attribute it to a specific tenant and, where applicable, a specific staff identity

### Requirement: Credential hygiene
The system SHALL NOT allow any access token, refresh token, or client secret to appear in a log line, a model prompt, or a tool description, under any code path.

#### Scenario: Credential redaction
- **WHEN** any logging or prompt-construction code path executes
- **THEN** no raw token or secret value is present in the output
