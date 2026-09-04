"""Real, separate agent code per vertical and per client
(openspec/changes/client-vertical-agent-classes) — a further, deliberate
reversal beyond openspec/changes/separate-vertical-client-agents, which
persisted vertical/client agent configuration as database rows
specifically so it could be edited without a code deploy. This package
reverses that specific tradeoff: `vertical_agent_templates` and
`client_agent_instances` are gone; a vertical's and a client's agent
behavior now lives in real, version-controlled Python classes instead,
accepting a code deploy per edit in exchange for genuinely separate,
reviewable implementations. See design.md's Context for the full
reasoning and history of this recurring decision.

- `base.py`: `BaseAgent` — the tool-calling loop mechanics shared by
  every vertical and every client, because the Anthropic tool-use API
  shape forces them to be identical, not because of a business decision.
- `verticals/`: one subclass per business vertical.
- `clients/`: one subclass per client, importing its vertical's class.
- `registry.py`: hub_id -> client agent class lookup.
"""
