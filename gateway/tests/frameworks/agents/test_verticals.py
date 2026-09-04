"""Confirms each real vertical class reads its raw framework text from
analysis_content (task 2.2) — this table is not moving into code, only
the vertical_agent_templates layer is."""

import pytest

from frameworks.agents.verticals.ecommerce import EcommerceAgent
from frameworks.agents.verticals.marketplace import MarketplaceAgent
from frameworks.agents.verticals.plg import PLGAgent
from frameworks.agents.verticals.saas import SaaSAgent
from frameworks.agents.verticals.services_project import ServicesProjectAgent
from frameworks.agents.verticals.transactional import TransactionalAgent
from frameworks.store import CONTENT_TYPE_FRAMEWORK, ingest

_VERTICAL_CLASSES = [SaaSAgent, PLGAgent, MarketplaceAgent, EcommerceAgent, ServicesProjectAgent, TransactionalAgent]


@pytest.mark.parametrize("agent_class", _VERTICAL_CLASSES, ids=lambda c: c.VERTICAL)
@pytest.mark.asyncio
async def test_vertical_class_reads_its_own_stored_framework_text(agent_class):
    await ingest(CONTENT_TYPE_FRAMEWORK, agent_class.VERTICAL, f"real framework content for {agent_class.VERTICAL}")

    class _Client(agent_class):
        HUB_ID = "hub_verticals_test"

    system = await _Client()._system_prompt()

    assert f"real framework content for {agent_class.VERTICAL}" in system


def test_every_known_vertical_has_its_own_agent_class():
    from frameworks.vertical import KNOWN_VERTICALS

    covered = {c.VERTICAL for c in _VERTICAL_CLASSES}
    assert covered == set(KNOWN_VERTICALS)
