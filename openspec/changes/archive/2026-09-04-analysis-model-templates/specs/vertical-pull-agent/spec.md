## ADDED Requirements

### Requirement: The pull agent gathers data; it never interprets or diagnoses it
The pull agent SHALL only decide which of the existing allowlisted HubSpot pull methods to call and with what parameters. It SHALL NOT produce, or be asked to produce, any interpretation, diagnosis, prioritization, or business judgment about what the gathered data means for a client — that remains the excluded analysis-job boundary (`HubSpot_MCP_Server_Spec_v1.2.md` Section 1.2, reconfirmed in `design.md`).

#### Scenario: The agent's output is raw gathered records, not a finding
- **WHEN** a pull-agent run completes for a tenant
- **THEN** its output is the same shape as `pull_crm_objects()`'s existing return value (object type → list of raw records), never a diagnostic statement, recommendation, or prioritized backlog item

### Requirement: The agent's tool surface is limited to the existing allowlisted pull methods
The pull agent SHALL call only tools that wrap already-allowlisted, already-tested methods on `HubSpotDataPullClient` (e.g. `pull_crm_objects`, `pull_object` for read-safe tool names). It SHALL NOT gain any HubSpot access path that a human-written pull could not also reach, and SHALL NOT construct or accept arbitrary SQL, tool names, or parameters from the model without passing through the existing `_is_read_safe`/`_is_safe_select` checks.

#### Scenario: The agent cannot call an unsafe or out-of-allowlist tool
- **WHEN** the agent's reasoning selects a tool name or SQL string that `_is_read_safe`/`_is_safe_select` would reject
- **THEN** the call is refused before it reaches HubSpot, the same way it already is for every non-agent caller of these methods

### Requirement: One shared agent configuration per vertical, not a copy per client
Each vertical SHALL have exactly one agent configuration (system prompt derived from that vertical's stored framework, plus the restricted tool surface), reused unmodified across every client of that vertical. Per-client customization SHALL happen only via data injected into an individual call (the client's onboarding profile, goals, and identity), never via a separate persisted agent configuration maintained per client.

#### Scenario: Two clients of the same vertical use the same agent configuration
- **WHEN** a pull-agent run is started for client A and, separately, for client B, both identified as "SaaS"
- **THEN** both runs reference the same stored SaaS agent configuration, and neither run's injected client data is visible to or reusable by the other

### Requirement: Context assembly for one tenant reads only that tenant's own data
Building a pull-agent request for a tenant SHALL source every piece of injected context — onboarding profile, goals, HubSpot connection — exclusively from that tenant's own records.

#### Scenario: Building tenant A's request never reads tenant B's data
- **WHEN** a pull-agent request is assembled for tenant A
- **THEN** no onboarding profile, goal, or HubSpot record belonging to any other tenant is read or included

### Requirement: A single pull-agent call never contains more than one tenant's data
An assembled pull-agent request SHALL contain exactly one tenant's data, even when a scheduled process is handling multiple tenants in the same run.

#### Scenario: A batch run never merges two tenants into one call
- **WHEN** a scheduled process runs the pull agent for several tenants in the same cycle
- **THEN** each individual API call's content is traceable to exactly one tenant, never a merged or batched set

### Requirement: Concurrent pulls for different tenants never cross-contaminate
When pull-agent runs for two different tenants execute concurrently, neither run's context assembly SHALL read, cache, or otherwise expose any data belonging to the other tenant.

#### Scenario: Two tenants pulled at the same time stay isolated
- **WHEN** tenant A's and tenant B's pull-agent runs are in flight at the same time
- **THEN** inspecting either run's assembled request or tool-call history shows no trace of the other tenant's data

### Requirement: Every tool call the agent makes mid-loop is bound to the run's one tenant
Regardless of how many tool calls the agent decides to make, or in what order, every one of them SHALL execute against the vaulted HubSpot connection for the single tenant that run was started for.

#### Scenario: A tool call the agent decides to make stays bound to the right tenant
- **WHEN** the agent, partway through a run for tenant A, decides to call a pull tool it hadn't called yet
- **THEN** that call still executes using tenant A's vaulted connection, never any other tenant's

### Requirement: A retried request rebuilds context fresh
When a pull-agent request fails and is retried, the retry SHALL rebuild its context from that tenant's current data rather than reusing any cached or stale context from the failed attempt.

#### Scenario: A retry after failure doesn't reuse stale or wrong-tenant context
- **WHEN** a pull-agent request for tenant A fails and is retried
- **THEN** the retried request's context is freshly assembled from tenant A's data, not carried over from the failed attempt

### Requirement: Every pull-agent run is attributable to the correct tenant in the audit log
A pull-agent run, successful or failed, SHALL be recorded in the audit log with the correct `hub_id`, using the same event-logging convention as every other pull path in this project.

#### Scenario: A pull-agent run is traceable to one tenant after the fact
- **WHEN** a pull-agent run completes or fails
- **THEN** the audit log contains an entry with that tenant's `hub_id`, unambiguous about which tenant it belongs to

### Requirement: The agent's tool-calling loop is bounded
A single pull-agent run SHALL be bounded by a maximum number of tool calls, so a run cannot loop indefinitely or accumulate unbounded cost.

#### Scenario: A run that would loop excessively is stopped
- **WHEN** the agent's reasoning would otherwise continue calling tools past the configured maximum
- **THEN** the run stops and returns whatever it has gathered so far, rather than continuing unbounded
