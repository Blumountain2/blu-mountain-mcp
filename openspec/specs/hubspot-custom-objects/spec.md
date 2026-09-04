# hubspot-custom-objects Specification

## Purpose
Generic, read-only access to a HubSpot portal's own custom objects — discovering a tenant's real custom object schemas at runtime (there is no fixed lookup table for these the way there is for standard CRM object types) and reading one's records by its discovered `objectTypeId`, using the same paginated pull path every standard object already uses.

## Requirements
### Requirement: Discover a tenant's custom object schemas
The system SHALL discover every custom object schema defined on a tenant's portal at call time, via HubSpot's schema API, returning each schema's `objectTypeId`, name, and labels. No custom object identifier SHALL ever be hand-enumerated or assumed ahead of time — every tenant's custom objects are discovered fresh, per call, the same way custom properties already are.

#### Scenario: A real portal with a custom object returns it
- **WHEN** custom object schema discovery is called for a tenant whose portal has at least one real custom object defined
- **THEN** the response includes that object's real `objectTypeId` and name

#### Scenario: A portal with no Custom Objects access degrades gracefully
- **WHEN** custom object schema discovery is called for a tenant whose portal lacks Custom Objects access (no Enterprise-tier grant, or the scope wasn't granted)
- **THEN** the system returns an empty result rather than raising an uncaught error

### Requirement: Read one custom object's records by its discovered identifier
The system SHALL read a custom object's records given its `objectTypeId`, using the same paginated, read-only GET pattern already used for every standard CRM object type. The system SHALL NOT accept a friendly name in place of a real, previously-discovered `objectTypeId` — a caller must resolve the identifier via schema discovery first.

#### Scenario: Records are read for a real custom object
- **WHEN** a real, previously-discovered `objectTypeId` is used to read records
- **THEN** the real records for that custom object are returned, paginated the same way standard objects are

#### Scenario: A pull failure for one custom object does not crash the caller
- **WHEN** reading a custom object's records fails (e.g. a 403 from insufficient scope or tier)
- **THEN** the system returns a failure marker rather than raising an uncaught exception

### Requirement: Discover a custom object's own properties, including custom-vs-standard status
The system SHALL discover every real property defined on a custom object type, reusing the same properties-discovery mechanism already used for standard CRM objects, keyed by the custom object's `objectTypeId` instead of a fixed slug.

#### Scenario: Custom object properties are discoverable the same way standard object properties are
- **WHEN** property discovery is called with a real custom object's `objectTypeId`
- **THEN** the real property definitions for that custom object are returned

### Requirement: Custom object access is read-only and tenant-isolated, same as every other HubSpot access path
No write-shaped call SHALL ever be made against a custom object, and every call SHALL be scoped to exactly one tenant's own vaulted token, with no mechanism for one tenant's custom object discovery or read to reach another tenant's data.

#### Scenario: Only GET requests are made
- **WHEN** any custom-object discovery or read method is called
- **THEN** every HTTP request it makes is a GET request, never a write-shaped method

#### Scenario: A tenant's custom object pull never uses another tenant's token
- **WHEN** custom object discovery or reads are performed for two different tenants
- **THEN** each tenant's calls use only that tenant's own vaulted access token

