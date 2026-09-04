"""pull_agent.run_client_agent is now a thin wrapper (openspec/changes/
client-vertical-agent-classes) — it looks up hub_id's registered agent
class and runs it. The actual loop mechanics, tool dispatch, isolation,
and audit logging it used to implement directly now live in
gateway/frameworks/agents/base.py, tested in
tests/frameworks/agents/test_base.py — not duplicated here."""

import pytest

from frameworks import pull_agent
from frameworks.agents import registry
from frameworks.agents.base import BaseAgent
from frameworks.agents.registry import register_client_agent
from frameworks.pull_agent import run_client_agent


@pytest.fixture(autouse=True)
def _clean_registry():
    before = set(registry._REGISTRY.keys())
    yield
    for hub_id in set(registry._REGISTRY.keys()) - before:
        del registry._REGISTRY[hub_id]


def test_real_clients_are_registered_just_by_importing_pull_agent():
    # pull_agent imports frameworks.agents.clients at module load time
    # specifically so callers never have to remember to import it
    # themselves before calling run_client_agent.
    assert registry.get_registered_agent_class("148997330") is not None
    assert registry.get_registered_agent_class("149094230") is not None


@pytest.mark.asyncio
async def test_run_client_agent_raises_clearly_for_an_unregistered_hub_id():
    with pytest.raises(ValueError, match="hub_totally_unregistered"):
        await run_client_agent("hub_totally_unregistered")


@pytest.mark.asyncio
async def test_run_client_agent_delegates_to_the_registered_classs_run(monkeypatch):
    calls = []

    @register_client_agent("hub_wrapper_test")
    class _FakeAgent(BaseAgent):
        VERTICAL = "saas"
        HUB_ID = "hub_wrapper_test"

        def __init__(self):
            # Skip BaseAgent's real HubSpotDataPullClient construction —
            # this test only proves the wrapper delegates, not that the
            # loop itself runs.
            self.hub_id = self.HUB_ID

        async def run(self):
            calls.append(self.hub_id)
            return {"CONTACT": []}

    result = await run_client_agent("hub_wrapper_test")

    assert calls == ["hub_wrapper_test"]
    assert result == {"CONTACT": []}
