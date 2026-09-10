"""Tests for BaseAgent (openspec/changes/client-vertical-agent-classes):
the tool-calling loop mechanics, moved unchanged in behavior from the
prior DB-driven run_client_agent — proven here independent of any real
vertical or client content, using a minimal dynamically-built test
subclass rather than the DB-backed fixtures the prior version of this
file needed.

The Anthropic API itself is never called in these tests — a fake client
scripts a sequence of responses so the loop, tool dispatch, and isolation
logic can be tested deterministically and for free."""

import asyncio

import pytest

from db import get_pool
from frameworks.agents import base, diagnostics
from frameworks.agents.base import MAX_TOOL_CALLS, BaseAgent
from sync.hubspot_client import HubSpotDataPullClient

DEFAULT_TEST_FRAMEWORK_TEXT = "Trust hs_object_id. Pull CONTACT and COMPANY."


async def _seed_tenant(hub_id: str) -> None:
    pool = await get_pool()
    await pool.execute("INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'installed')", hub_id)


def _agent_class(
    hub_id: str,
    vertical: str = "saas",
    confirmed_fields: dict | None = None,
    additions: str = "",
    max_tool_calls: int | None = None,
    framework_text: str = DEFAULT_TEST_FRAMEWORK_TEXT,
):
    """Builds a throwaway BaseAgent subclass for one test — the class-based
    equivalent of what _seed_client's DB fixtures used to construct.
    FRAMEWORK_TEXT is now a plain class attribute (openspec/changes/
    vertical-framework-content-in-code), not read from analysis_content,
    so tests set it directly rather than seeding the database."""
    attrs = {
        "VERTICAL": vertical,
        "HUB_ID": hub_id,
        "FRAMEWORK_TEXT": framework_text,
        "CONFIRMED_FIELDS": confirmed_fields or {},
        "SYSTEM_PROMPT_ADDITIONS": additions,
    }
    if max_tool_calls is not None:
        attrs["MAX_TOOL_CALLS"] = max_tool_calls
    return type(f"TestAgent_{hub_id}", (BaseAgent,), attrs)


async def _seed_client(hub_id: str, vertical: str = "saas", **kwargs):
    await _seed_tenant(hub_id)
    return _agent_class(hub_id, vertical=vertical, **kwargs)


# --- fake Anthropic client: scripts a fixed sequence of responses ---


class _FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, tool_id, name, tool_input):
        self.id = tool_id
        self.name = name
        self.input = tool_input


class _FakeResponse:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return self._responses.pop(0)


class _FakeAsyncAnthropic:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)

    def __call__(self, *args, **kwargs):
        return self


def _one_pull_then_stop(object_type: str = "CONTACT"):
    return [
        _FakeResponse("tool_use", [_FakeToolUseBlock("call_1", "pull_object_type", {"object_type": object_type})]),
        _FakeResponse("end_turn", [_FakeTextBlock("done")]),
    ]


def _list_then_pull_then_stop(object_type: str = "CONTACT"):
    return [
        _FakeResponse("tool_use", [_FakeToolUseBlock("call_1", "list_object_types", {})]),
        _FakeResponse(
            "tool_use", [_FakeToolUseBlock("call_2", "pull_object_type", {"object_type": object_type})]
        ),
        _FakeResponse("end_turn", [_FakeTextBlock("done")]),
    ]


def _patch_anthropic(monkeypatch, responses):
    fake = _FakeAsyncAnthropic(responses)
    monkeypatch.setattr(base, "AsyncAnthropic", fake)
    return fake


def _patch_hubspot(monkeypatch, records_for=None):
    """records_for: optional fn(hub_id, object_type) -> list[dict]. Default
    tags every record with the hub_id it was pulled for, so a test can
    assert no tenant's records ever end up under another tenant's key."""
    if records_for is None:

        def records_for(hub_id, object_type):
            return [{"properties": {"hub_id_tag": hub_id, "object_type": object_type}}]

    async def fake_pull_crm_objects(self, client=None, headers=None, object_types=None, properties=None):
        object_type = object_types[0]
        return {object_type: records_for(self.hub_id, object_type)}

    monkeypatch.setattr(HubSpotDataPullClient, "pull_crm_objects", fake_pull_crm_objects)


# --- BaseAgent alone, no real vertical/client content ---


@pytest.mark.asyncio
async def test_base_agent_loop_works_with_no_real_vertical_or_client_content(monkeypatch):
    agent_class = await _seed_client("hub_a", vertical="saas")
    _patch_hubspot(monkeypatch)
    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    result = await agent_class().run()

    assert result == {"CONTACT": [{"properties": {"hub_id_tag": "hub_a", "object_type": "CONTACT"}}]}


def test_a_bare_vertical_class_with_no_hub_id_refuses_to_construct():
    class SaaSLikeAgent(BaseAgent):
        VERTICAL = "saas"

    with pytest.raises(ValueError, match="HUB_ID"):
        SaaSLikeAgent()


# --- gathering only, never analysis ---


@pytest.mark.asyncio
async def test_output_shape_matches_pull_crm_objects_not_a_finding(monkeypatch):
    agent_class = await _seed_client("hub_a")
    _patch_hubspot(monkeypatch)
    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    result = await agent_class().run()

    assert result == {"CONTACT": [{"properties": {"hub_id_tag": "hub_a", "object_type": "CONTACT"}}]}
    assert "recommendations" not in result
    assert "priority" not in result


# --- restricted tool surface ---


@pytest.mark.asyncio
async def test_unknown_object_type_is_refused_before_touching_hubspot(monkeypatch):
    agent_class = await _seed_client("hub_a")
    pull_calls = []

    async def fake_pull_crm_objects(self, client=None, headers=None, object_types=None, properties=None):
        pull_calls.append(object_types)
        return {object_types[0]: []}

    monkeypatch.setattr(HubSpotDataPullClient, "pull_crm_objects", fake_pull_crm_objects)
    _patch_anthropic(
        monkeypatch,
        [
            _FakeResponse(
                "tool_use",
                [_FakeToolUseBlock("call_1", "pull_object_type", {"object_type": "NOT_A_REAL_TYPE"})],
            ),
            _FakeResponse("end_turn", [_FakeTextBlock("done")]),
        ],
    )

    result = await agent_class().run()

    assert result == {}
    assert pull_calls == []


# --- confirmed fields narrow the pull ---


@pytest.mark.asyncio
async def test_confirmed_fields_narrow_what_is_requested(monkeypatch):
    agent_class = await _seed_client("hub_a", confirmed_fields={"CONTACT": ["health_score", "plan_tier"]})
    captured_properties = {}

    async def fake_pull_crm_objects(self, client=None, headers=None, object_types=None, properties=None):
        object_type = object_types[0]
        captured_properties[object_type] = (properties or {}).get(object_type)
        return {object_type: [{"properties": {}}]}

    async def fake_discover(self, object_type, client=None, headers=None):
        raise AssertionError("discovery should be skipped when fields are already confirmed")

    monkeypatch.setattr(HubSpotDataPullClient, "pull_crm_objects", fake_pull_crm_objects)
    monkeypatch.setattr(HubSpotDataPullClient, "discover_object_properties", fake_discover)
    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    await agent_class().run()

    assert captured_properties["CONTACT"] == ["health_score", "plan_tier"]


@pytest.mark.asyncio
async def test_no_confirmed_fields_falls_back_to_full_discovery(monkeypatch):
    agent_class = await _seed_client("hub_a", confirmed_fields={})
    discovery_calls = []

    async def fake_discover(self, object_type, client=None, headers=None):
        discovery_calls.append(object_type)
        return ["some_discovered_field"]

    async def fake_pull_crm_objects(self, client=None, headers=None, object_types=None, properties=None):
        return {object_types[0]: [{"properties": {}}]}

    monkeypatch.setattr(HubSpotDataPullClient, "discover_object_properties", fake_discover)
    monkeypatch.setattr(HubSpotDataPullClient, "pull_crm_objects", fake_pull_crm_objects)
    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    await agent_class().run()

    assert discovery_calls == ["CONTACT"]


@pytest.mark.asyncio
async def test_two_client_classes_of_the_same_vertical_get_genuinely_different_requests(monkeypatch):
    agent_a = await _seed_client("hub_a", confirmed_fields={"COMPANY": ["employee_count"]})
    agent_b = _agent_class("hub_b", vertical="saas", confirmed_fields={"COMPANY": ["priority_level"]})
    _patch_hubspot(monkeypatch)

    fake_a = _patch_anthropic(monkeypatch, _one_pull_then_stop("COMPANY"))
    await agent_a().run()

    fake_b = _patch_anthropic(monkeypatch, _one_pull_then_stop("COMPANY"))
    await agent_b().run()

    content_a = fake_a.messages.requests[0]["messages"][0]["content"]
    content_b = fake_b.messages.requests[0]["messages"][0]["content"]

    # Same vertical, so the shared system prompt is identical...
    assert fake_a.messages.requests[0]["system"] == fake_b.messages.requests[0]["system"]
    # ...but the per-client user message genuinely differs.
    assert content_a != content_b
    assert "employee_count" in content_a and "employee_count" not in content_b
    assert "priority_level" in content_b and "priority_level" not in content_a


@pytest.mark.asyncio
async def test_a_client_with_no_confirmed_fields_gets_the_generic_message(monkeypatch):
    agent_class = await _seed_client("hub_a", confirmed_fields={})
    _patch_hubspot(monkeypatch)
    fake = _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    await agent_class().run()

    content = fake.messages.requests[0]["messages"][0]["content"]
    assert "No fields have been confirmed relevant for this client yet." in content


# --- concurrent pulls for different tenants never cross-contaminate ---


@pytest.mark.asyncio
async def test_concurrent_runs_for_two_tenants_never_cross_contaminate(monkeypatch):
    agent_a = await _seed_client("hub_a")
    agent_b = _agent_class("hub_b", vertical="saas")
    _patch_hubspot(monkeypatch)

    scripts = {"hub_a": _list_then_pull_then_stop("CONTACT"), "hub_b": _list_then_pull_then_stop("COMPANY")}
    call_index = {"n": 0}
    fakes = [_FakeAsyncAnthropic(scripts["hub_a"]), _FakeAsyncAnthropic(scripts["hub_b"])]

    def fake_constructor(*args, **kwargs):
        fake = fakes[call_index["n"]]
        call_index["n"] += 1
        return fake

    monkeypatch.setattr(base, "AsyncAnthropic", fake_constructor)

    result_a, result_b = await asyncio.gather(agent_a().run(), agent_b().run())

    assert set(result_a.keys()) == {"CONTACT"}
    assert result_a["CONTACT"][0]["properties"]["hub_id_tag"] == "hub_a"
    assert set(result_b.keys()) == {"COMPANY"}
    assert result_b["COMPANY"][0]["properties"]["hub_id_tag"] == "hub_b"


# --- every tool call mid-loop stays bound to the run's one tenant ---


@pytest.mark.asyncio
async def test_every_mid_loop_tool_call_stays_bound_to_the_runs_tenant(monkeypatch):
    agent_class = await _seed_client("hub_a")
    constructed_hub_ids = []
    real_init = HubSpotDataPullClient.__init__

    def _recording_init(self, hub_id):
        constructed_hub_ids.append(hub_id)
        real_init(self, hub_id)

    monkeypatch.setattr(HubSpotDataPullClient, "__init__", _recording_init)
    _patch_hubspot(monkeypatch)
    _patch_anthropic(monkeypatch, _list_then_pull_then_stop("CONTACT"))

    await agent_class().run()

    # Exactly one HubSpotDataPullClient constructed for the whole run,
    # regardless of how many tool calls happened inside it.
    assert constructed_hub_ids == ["hub_a"]


@pytest.mark.asyncio
async def test_two_sequential_runs_for_the_same_tenant_dont_share_pull_state(monkeypatch):
    agent_class = await _seed_client("hub_a")
    _patch_hubspot(monkeypatch)

    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))
    first = await agent_class().run()

    _patch_anthropic(monkeypatch, _one_pull_then_stop("COMPANY"))
    second = await agent_class().run()

    assert set(first.keys()) == {"CONTACT"}
    assert set(second.keys()) == {"COMPANY"}


# --- every run is attributable to the correct tenant in the audit log ---


@pytest.mark.asyncio
async def test_successful_run_is_audited_under_the_correct_hub_id(monkeypatch):
    agent_class = await _seed_client("hub_a")
    _patch_hubspot(monkeypatch)
    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    await agent_class().run()

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT hub_id, event_type FROM audit_log WHERE event_type = 'pull_agent_run_completed'"
    )
    assert row["hub_id"] == "hub_a"


@pytest.mark.asyncio
async def test_failed_run_is_audited_under_the_correct_hub_id_and_reraises(monkeypatch):
    agent_class = await _seed_client("hub_a")

    async def fake_pull_crm_objects(self, client=None, headers=None, object_types=None, properties=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(HubSpotDataPullClient, "pull_crm_objects", fake_pull_crm_objects)
    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    with pytest.raises(RuntimeError):
        await agent_class().run()

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT hub_id, event_type FROM audit_log WHERE event_type = 'pull_agent_run_failed'"
    )
    assert row["hub_id"] == "hub_a"


@pytest.mark.asyncio
async def test_the_original_failure_survives_even_if_the_audit_write_also_fails(monkeypatch):
    agent_class = await _seed_client("hub_a")

    async def fake_pull_crm_objects(self, client=None, headers=None, object_types=None, properties=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(HubSpotDataPullClient, "pull_crm_objects", fake_pull_crm_objects)
    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    from auth import security

    async def failing_record_audit(*args, **kwargs):
        raise RuntimeError("audit_log insert failed")

    monkeypatch.setattr(security, "record_audit", failing_record_audit)

    with pytest.raises(RuntimeError, match="boom"):
        await agent_class().run()


# --- the agent's tool-calling loop is bounded ---


@pytest.mark.asyncio
async def test_a_run_that_would_loop_past_the_budget_stops_gracefully(monkeypatch):
    agent_class = await _seed_client("hub_a")
    _patch_hubspot(monkeypatch)

    over_budget_script = [
        _FakeResponse("tool_use", [_FakeToolUseBlock(f"call_{i}", "list_object_types", {})])
        for i in range(MAX_TOOL_CALLS + 5)
    ]
    fake = _patch_anthropic(monkeypatch, over_budget_script)

    result = await agent_class().run()

    assert len(fake.messages.requests) == MAX_TOOL_CALLS + 1
    assert result == {}


@pytest.mark.asyncio
async def test_a_client_class_can_override_the_default_budget(monkeypatch):
    agent_class = await _seed_client("hub_a", max_tool_calls=2)

    over_budget_script = [
        _FakeResponse("tool_use", [_FakeToolUseBlock(f"call_{i}", "list_object_types", {})])
        for i in range(10)
    ]
    fake = _patch_anthropic(monkeypatch, over_budget_script)

    result = await agent_class().run()

    assert len(fake.messages.requests) == 3
    assert result == {}


# --- a client class with no framework text refuses to construct ---


def test_a_client_class_with_no_framework_text_refuses_to_construct():
    agent_class = _agent_class("hub_a", vertical="a-vertical-with-no-framework-text", framework_text="")

    with pytest.raises(ValueError, match="FRAMEWORK_TEXT"):
        agent_class()


# --- custom object reach ---


@pytest.mark.asyncio
async def test_list_custom_objects_then_pull_custom_object(monkeypatch):
    agent_class = await _seed_client("hub_a")

    async def fake_discover_schemas(self, client=None, headers=None):
        return [{"objectTypeId": "2-123", "name": "transactions", "labels": {"singular": "Transaction"}}]

    async def fake_discover_properties(self, object_type_id, client=None, headers=None):
        return [{"name": "amount", "hubspotDefined": False}]

    async def fake_pull_custom_object(self, object_type_id, client=None, headers=None, properties=None):
        assert object_type_id == "2-123"
        assert properties == ["amount"]
        return [{"id": "1", "properties": {"amount": "100"}}]

    monkeypatch.setattr(HubSpotDataPullClient, "discover_custom_object_schemas", fake_discover_schemas)
    monkeypatch.setattr(HubSpotDataPullClient, "discover_custom_object_properties", fake_discover_properties)
    monkeypatch.setattr(HubSpotDataPullClient, "pull_custom_object", fake_pull_custom_object)
    _patch_anthropic(
        monkeypatch,
        [
            _FakeResponse("tool_use", [_FakeToolUseBlock("call_1", "list_custom_objects", {})]),
            _FakeResponse(
                "tool_use",
                [_FakeToolUseBlock("call_2", "pull_custom_object", {"object_type_id": "2-123"})],
            ),
            _FakeResponse("end_turn", [_FakeTextBlock("done")]),
        ],
    )

    result = await agent_class().run()

    assert result == {"2-123": [{"id": "1", "properties": {"amount": "100"}}]}


@pytest.mark.asyncio
async def test_pull_custom_object_uses_confirmed_fields_when_present(monkeypatch):
    agent_class = await _seed_client("hub_a", confirmed_fields={"2-123": ["status"]})

    async def fake_discover_properties(self, object_type_id, client=None, headers=None):
        raise AssertionError("discovery should be skipped when fields are already confirmed")

    async def fake_pull_custom_object(self, object_type_id, client=None, headers=None, properties=None):
        assert properties == ["status"]
        return [{"id": "1", "properties": {"status": "open"}}]

    monkeypatch.setattr(HubSpotDataPullClient, "discover_custom_object_properties", fake_discover_properties)
    monkeypatch.setattr(HubSpotDataPullClient, "pull_custom_object", fake_pull_custom_object)
    _patch_anthropic(
        monkeypatch,
        [
            _FakeResponse(
                "tool_use",
                [_FakeToolUseBlock("call_1", "pull_custom_object", {"object_type_id": "2-123"})],
            ),
            _FakeResponse("end_turn", [_FakeTextBlock("done")]),
        ],
    )

    result = await agent_class().run()

    assert result == {"2-123": [{"id": "1", "properties": {"status": "open"}}]}


@pytest.mark.asyncio
async def test_a_portal_without_custom_object_access_degrades_gracefully(monkeypatch):
    agent_class = await _seed_client("hub_a")

    async def fake_discover_schemas(self, client=None, headers=None):
        return []  # matches discover_custom_object_schemas's own real degrade-to-[] contract

    monkeypatch.setattr(HubSpotDataPullClient, "discover_custom_object_schemas", fake_discover_schemas)
    _patch_anthropic(
        monkeypatch,
        [
            _FakeResponse("tool_use", [_FakeToolUseBlock("call_1", "list_custom_objects", {})]),
            _FakeResponse("end_turn", [_FakeTextBlock("done")]),
        ],
    )

    result = await agent_class().run()

    assert result == {}


# --- the diagnostic phase (openspec/changes/vertical-diagnostic-agent) ---


@pytest.mark.asyncio
async def test_diagnose_returns_a_narrative_not_the_raw_records_shape(monkeypatch):
    agent_class = await _seed_client("hub_a")
    report = {"summary": "All healthy.", "kpis": [], "risk_flags": []}

    async def fake_produce_diagnostic_report(**kwargs):
        return report

    monkeypatch.setattr(diagnostics, "produce_diagnostic_report", fake_produce_diagnostic_report)

    result = await agent_class().diagnose({"CONTACT": [{"properties": {}}]})

    assert result == report
    assert "CONTACT" not in result


@pytest.mark.asyncio
async def test_diagnose_passes_only_this_runs_own_gathered_data_through(monkeypatch):
    agent_class = await _seed_client("hub_a")
    captured = {}

    async def fake_produce_diagnostic_report(vertical, framework_text, client_name, system_prompt_additions, gathered):
        captured["gathered"] = gathered
        captured["vertical"] = vertical
        captured["framework_text"] = framework_text
        captured["client_name"] = client_name
        return {"summary": "ok", "kpis": [], "risk_flags": []}

    monkeypatch.setattr(diagnostics, "produce_diagnostic_report", fake_produce_diagnostic_report)
    tenant_a_gathered = {"CONTACT": [{"properties": {"hub_id_tag": "hub_a"}}]}

    await agent_class().diagnose(tenant_a_gathered)

    assert captured["gathered"] is tenant_a_gathered
    assert captured["vertical"] == "saas"
    assert captured["framework_text"] == DEFAULT_TEST_FRAMEWORK_TEXT
    assert captured["client_name"] == "hub_a"  # falls back to HUB_ID when CLIENT_NAME unset


@pytest.mark.asyncio
async def test_diagnose_has_no_hubspot_client_of_its_own(monkeypatch):
    agent_class = await _seed_client("hub_a")

    async def fake_produce_diagnostic_report(**kwargs):
        return {"summary": "ok", "kpis": [], "risk_flags": []}

    monkeypatch.setattr(diagnostics, "produce_diagnostic_report", fake_produce_diagnostic_report)
    assert not hasattr(diagnostics, "HubSpotDataPullClient")

    await agent_class().diagnose({})


@pytest.mark.asyncio
async def test_successful_diagnostic_run_is_audited_under_the_correct_hub_id(monkeypatch):
    agent_class = await _seed_client("hub_a")

    async def fake_produce_diagnostic_report(**kwargs):
        return {"summary": "ok", "kpis": [], "risk_flags": []}

    monkeypatch.setattr(diagnostics, "produce_diagnostic_report", fake_produce_diagnostic_report)

    await agent_class().diagnose({})

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT hub_id, event_type FROM audit_log WHERE event_type = 'diagnostic_run_completed'"
    )
    assert row["hub_id"] == "hub_a"


@pytest.mark.asyncio
async def test_failed_diagnostic_run_is_audited_under_the_correct_hub_id_and_reraises(monkeypatch):
    agent_class = await _seed_client("hub_a")

    async def failing_produce_diagnostic_report(**kwargs):
        raise RuntimeError("diagnostic boom")

    monkeypatch.setattr(diagnostics, "produce_diagnostic_report", failing_produce_diagnostic_report)

    with pytest.raises(RuntimeError, match="diagnostic boom"):
        await agent_class().diagnose({})

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT hub_id, event_type FROM audit_log WHERE event_type = 'diagnostic_run_failed'"
    )
    assert row["hub_id"] == "hub_a"
