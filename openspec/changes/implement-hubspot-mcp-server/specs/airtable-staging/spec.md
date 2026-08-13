## ADDED Requirements

### Requirement: Scheduled staging cycle
The system SHALL run a scheduled job that pulls each tenant's in-scope HubSpot data, normalizes it, and writes it into Airtable on a configurable interval.

#### Scenario: Scheduled run stages data
- **WHEN** the staging interval elapses
- **THEN** the system pulls, normalizes, and writes each active tenant's data into Airtable

### Requirement: Every record tagged by client
The system SHALL tag every record written to Airtable with the owning client's identifier.

#### Scenario: Tagged write
- **WHEN** a record is written to Airtable
- **THEN** it includes a client tag identifying which tenant it belongs to

### Requirement: Isolation preserved in staging writes
The system SHALL ensure that one tenant's pull can never write into, or be confused with, another tenant's staging rows.

#### Scenario: Cross-tenant write prevention
- **WHEN** tenant A's data is staged
- **THEN** it is never written into any table row tagged for tenant B, even under concurrent staging runs for multiple tenants
