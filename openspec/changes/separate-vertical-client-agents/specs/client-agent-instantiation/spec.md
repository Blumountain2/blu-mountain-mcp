## ADDED Requirements

### Requirement: Each client has its own persisted agent instance, not context re-assembled per call
The system SHALL persist one current agent instance per client, built from that client's vertical's current agent template plus that client's own injected documentation (onboarding-profile fields, confirmed custom fields, and any client-specific notes), versioned so producing a new instance never mutates a prior one.

#### Scenario: A client's instance persists across separate runs
- **WHEN** a pull-agent run completes for a client and a later run starts for the same client
- **THEN** both runs resolve the same persisted client agent instance, rather than each run re-deriving its own client-specific configuration from scratch

#### Scenario: A new instance version doesn't alter the prior one
- **WHEN** a client's agent instance is regenerated to a new version
- **THEN** the prior version remains stored, and the client's `hub_id` is associated with the latest version by default

### Requirement: A client agent instance is usable only for the client it was produced for
Structural isolation, matching the pattern already proven for `tenant_onboarding_profiles`: retrieving, resolving, or regenerating a client agent instance SHALL enforce `hub_id` directly in the query, never as a caller-supplied filter a bug could skip.

#### Scenario: A wrong hub_id cannot retrieve another client's instance
- **WHEN** a client agent instance is looked up using a `hub_id` that does not own it
- **THEN** the lookup returns nothing, indistinguishable from "no instance exists," never another client's instance

#### Scenario: Producing one client's instance never reads another client's data
- **WHEN** a client agent instance is produced for tenant A
- **THEN** no onboarding-profile field, custom-field guidance, or note belonging to any other tenant is read or included

### Requirement: A client agent instance is built only from that client's own vertical template
A client agent instance SHALL reference exactly one `vertical_agent_templates` version — the current version of the vertical assigned to that client at production time — and SHALL NOT combine configuration from more than one vertical.

#### Scenario: A client's instance matches its assigned vertical
- **WHEN** a client agent instance is produced for a tenant with vertical X
- **THEN** the instance references vertical X's current agent template, never a different vertical's

#### Scenario: A client with no assigned vertical cannot get an instance
- **WHEN** a client agent instance is requested for a tenant with no known vertical set
- **THEN** production is refused with a clear message, the same posture already established for onboarding profiles
