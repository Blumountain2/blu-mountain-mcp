## MODIFIED Requirements

### Requirement: The agent's tool surface is limited to the existing allowlisted pull methods
The pull agent SHALL call only tools that wrap already-allowlisted, already-tested methods on `HubSpotDataPullClient` (e.g. `pull_crm_objects`, `pull_object` for read-safe tool names). It SHALL NOT gain any HubSpot access path that a human-written pull could not also reach, and SHALL NOT construct or accept arbitrary endpoint paths, tool names, or parameters from the model without passing through the same hand-enumerated REST endpoint allowlist every other caller of these methods uses.

#### Scenario: The agent cannot call an unsafe or out-of-allowlist tool
- **WHEN** the agent's reasoning selects a tool name or object type outside the hand-enumerated REST endpoint allowlist
- **THEN** the call is refused before it reaches HubSpot, the same way it already is for every non-agent caller of these methods
