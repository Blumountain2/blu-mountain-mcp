## MODIFIED Requirements

### Requirement: The pull agent's gather phase gathers data; it never interprets or diagnoses it
The pull agent's gather phase (the bounded tool-calling loop over allowlisted HubSpot pull methods) SHALL only decide which of the existing allowlisted HubSpot pull methods to call and with what parameters. It SHALL NOT produce, or be asked to produce, any interpretation, diagnosis, prioritization, or business judgment about what the gathered data means for a client, and it SHALL NOT gain any tool or code path that lets the model do so from inside this phase's own loop. This holds regardless of which vertical or client agent class is running — none of them may override this behavior for the gather phase itself.

A distinct, separately-specified diagnostic phase (`vertical-diagnostic-reporting`) MAY run after the gather phase completes, consuming exactly that phase's output to produce a real interpretation. That diagnostic phase is not part of the gather phase, has no tool access of its own, and does not change anything about how the gather phase in this requirement behaves.

#### Scenario: The gather phase's output is raw gathered records, not a finding
- **WHEN** the gather phase of a run completes for a tenant
- **THEN** its own output is the same shape as `pull_crm_objects()`'s existing return value (object type → list of raw records), never a diagnostic statement, recommendation, or prioritized backlog item

#### Scenario: No client or vertical class can loosen the gather phase's own behavior
- **WHEN** any client's or vertical's agent class is authored
- **THEN** it inherits the gather phase's behavior from the base agent class and has no override point inside that phase to produce analysis instead of raw data

#### Scenario: A diagnostic phase consuming gather output does not change the gather phase itself
- **WHEN** a diagnostic phase (`vertical-diagnostic-reporting`) runs after a gather phase for the same tenant
- **THEN** the gather phase's own code, tool surface, and output shape are unaffected — it still returns only raw records, and the diagnostic phase's existence changes nothing about how it does so
