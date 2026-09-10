"""Tests for the hub_id -> client agent class registry
(openspec/changes/client-vertical-agent-classes)."""

import pytest

from frameworks.agents import registry
from frameworks.agents.base import BaseAgent
from frameworks.agents.registry import (
    DuplicateClientRegistration,
    get_registered_agent_class,
    register_client_agent,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    # Each test registers its own throwaway hub_ids into the real,
    # module-level registry — clear what this test adds afterward so
    # tests never see each other's registrations.
    before = set(registry._REGISTRY.keys())
    yield
    for hub_id in set(registry._REGISTRY.keys()) - before:
        del registry._REGISTRY[hub_id]


def test_a_registered_class_is_returned_for_its_hub_id():
    @register_client_agent("hub_registry_test_a")
    class _TestAgentA(BaseAgent):
        VERTICAL = "saas"
        HUB_ID = "hub_registry_test_a"

    assert get_registered_agent_class("hub_registry_test_a") is _TestAgentA


def test_an_unregistered_hub_id_raises_a_clear_error():
    with pytest.raises(ValueError, match="hub_registry_test_unregistered"):
        get_registered_agent_class("hub_registry_test_unregistered")


def test_registering_two_different_classes_under_the_same_hub_id_is_caught():
    @register_client_agent("hub_registry_test_dup")
    class _First(BaseAgent):
        VERTICAL = "saas"
        HUB_ID = "hub_registry_test_dup"

    with pytest.raises(DuplicateClientRegistration):
        @register_client_agent("hub_registry_test_dup")
        class _Second(BaseAgent):
            VERTICAL = "plg"
            HUB_ID = "hub_registry_test_dup"


def test_re_registering_the_exact_same_class_is_not_an_error():
    # Re-importing a module (e.g. under test collection) re-executes its
    # decorator — registering the identical class object twice must be a
    # no-op, not a false-positive duplicate error.
    @register_client_agent("hub_registry_test_reimport")
    class _Agent(BaseAgent):
        VERTICAL = "saas"
        HUB_ID = "hub_registry_test_reimport"

    register_client_agent("hub_registry_test_reimport")(_Agent)  # no raise


def test_vertical_for_hub_id_returns_the_registered_vertical():
    @register_client_agent("hub_registry_test_vertical")
    class _Agent(BaseAgent):
        VERTICAL = "marketplace"
        HUB_ID = "hub_registry_test_vertical"

    assert registry.vertical_for_hub_id("hub_registry_test_vertical") == "marketplace"


def test_vertical_for_hub_id_returns_none_for_an_unregistered_hub_id():
    # A tenant can be installed and permitted for a staff session before any
    # agent class has been authored for it — this must not raise, unlike
    # get_registered_agent_class.
    assert registry.vertical_for_hub_id("hub_registry_test_unregistered_vertical") is None
