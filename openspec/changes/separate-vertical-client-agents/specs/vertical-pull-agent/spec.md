## REMOVED Requirements

### Requirement: One shared agent configuration per vertical, not a copy per client
**Reason**: Superseded by a deliberate, leadership-directed reversal — see this change's `design.md` ("Decisions" and "Non-Negotiables" #6). This project now persists one agent instance per client, built from its vertical's own persisted template, rather than one ephemeral configuration re-derived and shared unmodified across every client of a vertical.
**Migration**: Replaced by `vertical-agent-templates`'s "Each vertical has its own persisted, independently-versioned agent template" requirement and `client-agent-instantiation`'s "Each client has its own persisted agent instance" requirement.

## ADDED Requirements

### Requirement: The pull agent resolves a persisted vertical template and client instance before running
Before a run starts, the pull agent SHALL resolve the tenant's current `client_agent_instances` row (producing one if absent) and that instance's referenced `vertical_agent_templates` row, and SHALL build its system prompt and tool/model configuration from those two persisted records rather than deriving them ad hoc from `analysis_content` alone.

#### Scenario: A run uses the tenant's persisted instance, not a freshly-derived one
- **WHEN** a pull-agent run starts for a tenant with an existing client agent instance
- **THEN** the run's system prompt and configuration are built from that instance's own referenced vertical template and injected documentation, not recomputed from raw framework content alone

#### Scenario: A run with no existing instance produces one before proceeding
- **WHEN** a pull-agent run starts for a tenant with no `client_agent_instances` row yet
- **THEN** one is produced from that tenant's vertical's current template and current onboarding profile before the run's request is assembled
