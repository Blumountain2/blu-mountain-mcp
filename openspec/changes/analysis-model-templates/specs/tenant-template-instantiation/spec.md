## ADDED Requirements

### Requirement: A tenant onboarding profile is produced from exactly one tenant's field profile
Producing a tenant onboarding profile SHALL take exactly one tenant's field-profiling result as input (optionally informed by that tenant's known vertical framework, per `tenant-field-profiling`'s requirements) and SHALL produce one tenant-specific onboarding profile as output. It SHALL NOT produce a profile that mixes field-profile data from more than one tenant.

#### Scenario: Producing a profile for one tenant never reads another tenant's data
- **WHEN** an onboarding profile is produced for tenant A
- **THEN** its field set is derived only from tenant A's own field-profiling result

### Requirement: An onboarding profile is a runtime parameterization input, not a copy of a framework or skill
A tenant onboarding profile SHALL contain only that tenant's confirmed-relevant fields and identifying information (tenant name, vertical). It SHALL NOT contain a copy, fork, or rewritten version of the vertical framework, the operational skill, or the runtime prompt — those remain shared and unmodified per `analysis-template-schema`'s requirements. The profile is designed to be supplied as a runtime parameter (alongside the unmodified framework) to whatever eventually invokes the skill, not as a substitute for the framework itself.

#### Scenario: Producing a profile does not alter the framework it references
- **WHEN** an onboarding profile is produced for a tenant identified as "SaaS"
- **THEN** the stored "SaaS" framework content is unchanged, and the profile itself contains no copy of that framework's instruction text

### Requirement: An onboarding profile is named after its tenant
An onboarding profile SHALL be named using that tenant's effective display name (the same resolution order already used elsewhere in this project: `portal_name`, falling back to `hub_domain`, falling back to `hub_id`), not a generic or vertical-only name.

#### Scenario: Two tenants of the same vertical get distinctly named profiles
- **WHEN** tenants "Acme Inc" and "Beta Co" are both profiled under the "SaaS" framework
- **THEN** the resulting onboarding profiles are named after "Acme Inc" and "Beta Co" respectively, not both named "SaaS"

### Requirement: Fields not confirmed relevant require human review before finalization
A field surfaced by profiling but not confirmed relevant by the tenant's known framework guidance SHALL be marked for human review, and an onboarding profile SHALL NOT be considered final while it has unreviewed candidate fields outstanding.

#### Scenario: A profile with unreviewed fields is not yet final
- **WHEN** profiling for a tenant surfaces one or more fields the framework's guidance doesn't address
- **THEN** the resulting onboarding profile is marked not final until a human reviews and confirms or rejects each one

### Requirement: A vertical is required to produce an onboarding profile, unless explicitly bypassed
Producing a tenant onboarding profile SHALL require a known vertical — either passed explicitly, or resolved from that tenant's own stored vertical (`frameworks.vertical.get_tenant_vertical`). If neither is available, production SHALL refuse with a clear, actionable message rather than silently proceeding with no framework guidance applied to any field. A caller MAY explicitly bypass this requirement by passing `allow_unqualified=True`, an explicit and deliberate choice rather than an accidental default.

#### Scenario: Producing a profile without a known vertical is refused
- **WHEN** a profile is requested for a tenant with no vertical passed explicitly and none stored
- **THEN** the request is refused with a message identifying the missing vertical, and no profile is produced

#### Scenario: A tenant's own stored vertical is used when none is passed explicitly
- **WHEN** a profile is requested for a tenant with a known stored vertical, and no vertical is passed explicitly
- **THEN** the tenant's own stored vertical is used, the same as if it had been passed explicitly

#### Scenario: An explicit override still allows an unqualified profile
- **WHEN** a profile is requested with `allow_unqualified=True` for a tenant with no known vertical
- **THEN** the profile is produced anyway, with every field's status determined by population alone, not framework guidance

### Requirement: An onboarding profile is usable only for the tenant it was produced for
An onboarding profile SHALL be scoped to exactly the one tenant it was produced for, and no code path SHALL be able to supply one tenant's onboarding profile as a runtime parameter for another tenant's data.

#### Scenario: Tenant B's data is never analyzed using tenant A's onboarding profile
- **WHEN** a run is requested for tenant B
- **THEN** only an onboarding profile produced for tenant B can be selected, never one produced for tenant A
