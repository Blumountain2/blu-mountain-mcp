## ADDED Requirements

### Requirement: Sybill webhook signature validation
The system SHALL validate the HMAC SHA-256 signature of incoming Sybill webhook payloads and SHALL reject any payload that is unsigned or older than five minutes.

#### Scenario: Valid signed payload
- **WHEN** a correctly signed, recent Sybill payload is received
- **THEN** the system accepts it for normalization and staging

#### Scenario: Unsigned or stale payload rejected
- **WHEN** a Sybill payload has an invalid or missing signature, or is older than five minutes
- **THEN** the system rejects it and does not stage any data from it

### Requirement: Transcript normalization and staging
The system SHALL normalize accepted Sybill call-transcript payloads and stage them into Airtable, tagged by the owning client.

#### Scenario: Transcript staged
- **WHEN** a valid Sybill payload is accepted
- **THEN** its transcript data is normalized and written into Airtable with the correct client tag
