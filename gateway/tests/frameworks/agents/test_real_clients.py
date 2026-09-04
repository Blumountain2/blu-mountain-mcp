"""Tests for the real, migrated client agent classes
(openspec/changes/client-vertical-agent-classes, task 4)."""

import pytest

from frameworks.agents import clients  # noqa: F401 — importing registers both real clients
from frameworks.agents.registry import get_registered_agent_class
from frameworks.agents.verticals.marketplace import MarketplaceAgent
from frameworks.agents.verticals.saas import SaaSAgent


def test_148997330_is_registered_as_a_saas_agent():
    cls = get_registered_agent_class("148997330")
    assert issubclass(cls, SaaSAgent)
    assert cls.HUB_ID == "148997330"


def test_149094230_is_registered_as_a_marketplace_agent():
    cls = get_registered_agent_class("149094230")
    assert issubclass(cls, MarketplaceAgent)
    assert cls.HUB_ID == "149094230"


def test_neither_real_client_has_confirmed_fields_yet():
    # Honest current state, matching the prior database's own
    # zero-confirmed-fields reality — this project shouldn't silently
    # invent confirmations that were never actually made by a human.
    assert get_registered_agent_class("148997330").CONFIRMED_FIELDS == {}
    assert get_registered_agent_class("149094230").CONFIRMED_FIELDS == {}


def test_two_real_clients_never_cross_read_each_others_confirmed_fields():
    a = get_registered_agent_class("148997330")
    b = get_registered_agent_class("149094230")
    a.CONFIRMED_FIELDS = {"CONTACT": ["only_a_should_have_this"]}
    try:
        assert "only_a_should_have_this" not in str(b.CONFIRMED_FIELDS)
        assert a.HUB_ID != b.HUB_ID
    finally:
        a.CONFIRMED_FIELDS = {}


@pytest.mark.asyncio
async def test_each_real_client_constructs_bound_to_only_its_own_hub_id():
    agent_a = get_registered_agent_class("148997330")()
    agent_b = get_registered_agent_class("149094230")()
    assert agent_a.hub_id == "148997330"
    assert agent_a.hs_client.hub_id == "148997330"
    assert agent_b.hub_id == "149094230"
    assert agent_b.hs_client.hub_id == "149094230"
