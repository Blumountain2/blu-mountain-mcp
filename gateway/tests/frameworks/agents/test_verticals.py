"""Confirms each real vertical class embeds its own real framework text
as a Python class attribute (openspec/changes/vertical-framework-content-
in-code) and that its system prompt includes that embedded content —
no longer read from analysis_content at request time."""

import pytest

from frameworks.agents.verticals.ecommerce import EcommerceAgent
from frameworks.agents.verticals.marketplace import MarketplaceAgent
from frameworks.agents.verticals.plg import PLGAgent
from frameworks.agents.verticals.saas import SaaSAgent
from frameworks.agents.verticals.services_project import ServicesProjectAgent
from frameworks.agents.verticals.transactional import TransactionalAgent

_VERTICAL_CLASSES = [SaaSAgent, PLGAgent, MarketplaceAgent, EcommerceAgent, ServicesProjectAgent, TransactionalAgent]


@pytest.mark.parametrize("agent_class", _VERTICAL_CLASSES, ids=lambda c: c.VERTICAL)
def test_vertical_class_has_real_non_empty_framework_text(agent_class):
    assert isinstance(agent_class.FRAMEWORK_TEXT, str)
    assert len(agent_class.FRAMEWORK_TEXT) > 1000  # a real framework document, not a placeholder


@pytest.mark.parametrize("agent_class", _VERTICAL_CLASSES, ids=lambda c: c.VERTICAL)
@pytest.mark.asyncio
async def test_vertical_class_system_prompt_includes_its_own_embedded_framework_text(agent_class):
    class _Client(agent_class):
        HUB_ID = "hub_verticals_test"

    system = await _Client()._system_prompt()

    assert agent_class.FRAMEWORK_TEXT in system


def test_every_vertical_class_has_its_own_distinct_framework_text():
    # Six real, different documents — none should accidentally share
    # content (e.g. a copy-paste of another vertical's file).
    texts = {c.VERTICAL: c.FRAMEWORK_TEXT for c in _VERTICAL_CLASSES}
    assert len(set(texts.values())) == len(texts)


def test_every_known_vertical_has_its_own_agent_class():
    from frameworks.vertical import KNOWN_VERTICALS

    covered = {c.VERTICAL for c in _VERTICAL_CLASSES}
    assert covered == set(KNOWN_VERTICALS)
