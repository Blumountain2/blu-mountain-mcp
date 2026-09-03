## ADDED Requirements

### Requirement: Field profiling reads only raw HubSpot object data
Tenant field profiling SHALL read a tenant's real object types and properties exclusively through the existing pull mechanism (`discover_hubspot_schema`/`pull_crm_objects`). It SHALL NOT call, nor depend on the output of, any HubSpot endpoint that returns workflows, reports, or other HubSpot-derived/aggregated analysis rather than raw object records.

#### Scenario: Profiling never touches a derived-data endpoint
- **WHEN** a tenant is profiled
- **THEN** every HubSpot call made during profiling is one already covered by the existing read-only allowlist (`_is_read_safe`/`_is_safe_select`), and none returns workflow, report, or analytics-derived data

### Requirement: Profiling is scoped to exactly one tenant's own connection
Field profiling for a tenant SHALL use only that tenant's own vaulted MCP Auth App connection, and SHALL NOT read, aggregate, or compare data across more than one tenant's connection in a single profiling run.

#### Scenario: Profiling one tenant never opens another tenant's connection
- **WHEN** tenant A is profiled
- **THEN** no connection is opened using tenant B's vaulted token at any point during that profiling run

### Requirement: Profiling identifies which fields are actually populated and in use
Field profiling SHALL produce, per relevant object type, the set of properties that are actually populated on real records for that tenant — not merely the full property schema HubSpot defines for that object type.

#### Scenario: An unpopulated custom field is distinguishable from a populated one
- **WHEN** a tenant's Contact object has a custom property that is defined in the schema but null on every real record
- **THEN** the profiling result marks that property as not populated, distinct from properties that do have real values

### Requirement: Profiling is informed by the relevant vertical framework's own default-trust guidance
When a tenant's vertical is already known, field profiling SHALL cross-reference the stored framework's own stated "properties to trust by default" and "properties to treat as unreliable by default" guidance for that vertical, rather than judging relevance from population statistics alone. Profiling MAY still run, producing an unqualified result, when no vertical is yet known for a tenant.

#### Scenario: A framework-flagged unreliable property is marked accordingly
- **WHEN** a tenant's known vertical framework states that `lifecyclestage` is unreliable by default for that vertical
- **THEN** the profiling result for that tenant flags `lifecyclestage` using that framework guidance, not solely its own population statistics
