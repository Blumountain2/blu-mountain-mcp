"""Entry point kept for backward-compatible call sites (`main.py`,
`debug_api.py`, `gateway/scripts/live_verification.py`) — the real
implementation moved to `gateway/frameworks/agents/` as part of
openspec/changes/client-vertical-agent-classes: real, separate,
version-controlled agent code per vertical and per client, replacing
the prior `vertical_agent_templates`/`client_agent_instances`
database-row-driven model this function used to assemble at call time.

`run_client_agent(hub_id)` now does nothing but look up hub_id's
registered agent class and run it — see `agents/registry.py` and
`agents/base.py` for what actually happens."""

from .agents import clients  # noqa: F401 — importing registers every real client
from .agents.base import MAX_TOOL_CALLS, ToolCallBudgetExceeded  # noqa: F401 — re-exported for existing importers
from .agents.registry import get_registered_agent_class


async def run_client_agent(hub_id: str) -> dict[str, list]:
    """Runs the registered agent for exactly one client. Raises ValueError
    if hub_id has no registered agent class (see registry.py) — there is
    no vertical/allow_unqualified fallback anymore: a tenant's agent is
    either a real, authored class or it doesn't run yet."""
    agent_class = get_registered_agent_class(hub_id)
    return await agent_class().run()
