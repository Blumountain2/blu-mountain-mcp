## REMOVED Requirements

### Requirement: The pull agent resolves a persisted vertical template and client instance before running
**Reason**: Superseded by a further, deliberate reversal — see this change's `design.md` Context. Leadership directed that vertical and client agent configuration be real, separate, version-controlled code rather than database rows a runtime lookup assembles. `vertical_agent_templates` and `client_agent_instances` are dropped entirely.
**Migration**: Replaced by `client-vertical-agent-classes`'s "Each vertical is its own subclass" and "Each client is its own subclass of its vertical" requirements. A tenant's agent is now resolved via a class registry, not a produced-or-fetched database row.

## MODIFIED Requirements

### Requirement: The pull agent gathers data; it never interprets or diagnoses it
The pull agent SHALL only decide which of the existing allowlisted HubSpot pull methods to call and with what parameters. It SHALL NOT produce, or be asked to produce, any interpretation, diagnosis, prioritization, or business judgment about what the gathered data means for a client — that remains the excluded analysis-job boundary (`HubSpot_MCP_Server_Spec_v1.2.md` Section 1.2, reconfirmed in `design.md`). This holds regardless of which vertical or client agent class is running — none of them may override this behavior.

#### Scenario: The agent's output is raw gathered records, not a finding
- **WHEN** a pull-agent run completes for a tenant
- **THEN** its output is the same shape as `pull_crm_objects()`'s existing return value (object type → list of raw records), never a diagnostic statement, recommendation, or prioritized backlog item

#### Scenario: No client or vertical class can loosen this rule
- **WHEN** any client's or vertical's agent class is authored
- **THEN** it inherits this behavior from the base agent class and has no override point to produce analysis instead of raw data
