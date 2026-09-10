## ADDED Requirements

### Requirement: A diagnostic phase produces a real interpretation, not raw records
After a client agent's gather phase completes, a distinct diagnostic phase SHALL reason over exactly that phase's gathered records against that client's vertical framework text and produce a diagnostic narrative (health/risk assessment, KPI report) — a real interpretation, not the same raw-records shape the gather phase returns.

#### Scenario: The diagnostic phase's output is a narrative, not a records dict
- **WHEN** the diagnostic phase completes for a client
- **THEN** its output is diagnostic narrative content, never the `object_type -> list[record]` shape the gather phase produces

#### Scenario: The diagnostic phase only reasons over data its own gather phase produced
- **WHEN** the diagnostic phase runs for tenant A
- **THEN** every fact it reasons over comes from tenant A's own gather-phase output for that same run, never a cached or unrelated run's data

### Requirement: The diagnostic phase does not gain its own HubSpot access
The diagnostic phase SHALL NOT call any HubSpot pull method, tool, or endpoint itself. It SHALL consume only the gather phase's already-produced output for that run.

#### Scenario: The diagnostic phase has no tool access
- **WHEN** the diagnostic phase is inspected
- **THEN** it has no HubSpot client, no tool definitions, and no code path that reaches `api.hubapi.com` directly or indirectly

### Requirement: The gather phase's existing guarantees are unaffected
Adding the diagnostic phase SHALL NOT change the gather phase's isolation, allowlisting, or bounded-loop behavior in any way. Every existing guarantee `vertical-pull-agent` establishes for the gather phase continues to hold unmodified.

#### Scenario: Gather-phase isolation tests pass unchanged
- **WHEN** the gather phase's existing isolation and allowlist tests are run after this capability is added
- **THEN** they pass without modification

### Requirement: A diagnostic report is obtainable on demand through the live MCP session
The live session SHALL expose a tool that, for the session's currently selected tenant, runs that tenant's gather phase followed by its diagnostic phase and returns the resulting narrative directly to the caller.

#### Scenario: A staff member requests a report for their selected tenant
- **WHEN** a staff member with a tenant already selected calls the diagnostic tool
- **THEN** the tool returns that tenant's diagnostic narrative, generated from that tenant's own real HubSpot data

#### Scenario: The tool requires a tenant to already be selected
- **WHEN** the diagnostic tool is called with no tenant selected in a session permitted more than one tenant
- **THEN** it is rejected the same way every other tenant-scoped live-session tool already requires a prior `select_tenant` call

#### Scenario: A tenant with no registered client agent class cannot produce a report
- **WHEN** the diagnostic tool is called for a tenant with no registered class in the agent registry
- **THEN** it fails with a clear error naming the missing registration, never silently substituting another tenant's or a generic configuration

### Requirement: A diagnostic report is staged into Airtable alongside synced HubSpot data
Every diagnostic report produced through the live-session tool SHALL also be staged into Airtable, tagged by client, in the same run that produced it.

#### Scenario: A generated report appears in Airtable
- **WHEN** a diagnostic report is returned to a staff member through the live-session tool
- **THEN** a corresponding record for that report exists in Airtable, tagged with that tenant's identity

#### Scenario: Staging failure does not silently hide from the caller
- **WHEN** staging a diagnostic report to Airtable fails
- **THEN** the failure is logged and audited distinctly from a successful staging, rather than reported to the caller as if staging succeeded

### Requirement: Every diagnostic run is audited by staff identity and tenant
A diagnostic run, successful or failed, SHALL be recorded in the audit log identifying the requesting staff member's identity and the tenant's `hub_id`, using the same audit convention as every other HubSpot-derived access in this project.

#### Scenario: A diagnostic run is traceable after the fact
- **WHEN** a diagnostic run completes or fails
- **THEN** the audit log contains an entry identifying which staff member requested it and which tenant it was for

### Requirement: The diagnostic phase reasons only over Blu Mountain's own authored framework content
The diagnostic phase's instructions SHALL be sourced from the stored, unmodified vertical framework and operational skill content (`analysis-template-schema`), never content authored, forked, or rewritten by this project.

#### Scenario: The diagnostic phase's prompt matches stored content exactly
- **WHEN** the diagnostic phase's system prompt is inspected for a given vertical
- **THEN** it matches that vertical's stored framework content exactly, with no project-authored interpretation logic substituted or added
