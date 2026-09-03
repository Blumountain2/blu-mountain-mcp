"""Task 8.5 tests (specs/vertical-pull-agent/spec.md), rewired by
openspec/changes/separate-vertical-client-agents (task 4.3) for the
two-tier vertical-template/client-instance model: the pull agent gathers
data only, never analysis; its tool surface is restricted to the existing
allowlisted pull methods; a run resolves its client's persisted agent
instance (producing one if absent) rather than deriving its request fresh
every call; and isolation holds even though the agent decides at runtime
which tools to call, unlike every other fixed pull path in this project.

The Anthropic API itself is never called in these tests — a fake client
scripts a sequence of responses so the loop, tool dispatch, and isolation
logic can be tested deterministically and for free. Real API confirmation
is task 8.7's job, not this file's.
"""

import asyncio

import pytest

from db import get_pool
from frameworks import onboarding, pull_agent
from frameworks.client_agent import get_latest_client_agent_instance, produce_client_agent_instance
from frameworks.onboarding import produce_onboarding_profile
from frameworks.profiling import FieldProfile
from frameworks.pull_agent import MAX_TOOL_CALLS, run_client_agent
from frameworks.store import CONTENT_TYPE_FRAMEWORK, ingest
from frameworks.vertical import set_tenant_vertical
from frameworks.vertical_templates import ingest_template
from sync.hubspot_client import HubSpotDataPullClient


def _fake_profiled(monkeypatch, result: dict):
    async def fake_profile_tenant_fields(hub_id, object_types, vertical=None):
        return result

    monkeypatch.setattr(onboarding, "profile_tenant_fields", fake_profile_tenant_fields)


async def _seed_tenant(hub_id: str) -> None:
    pool = await get_pool()
    await pool.execute("INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'installed')", hub_id)


async def _seed_framework(vertical: str = "saas", content: str = "Trust hs_object_id. Pull CONTACT and COMPANY.") -> None:
    await ingest(CONTENT_TYPE_FRAMEWORK, vertical, content)


async def _seed_template(vertical: str = "saas", additions: str = "", tool_config: dict | None = None) -> None:
    await ingest_template(vertical, additions, tool_config=tool_config)


async def _seed_client(
    hub_id: str,
    vertical: str = "saas",
    monkeypatch=None,
    profiled: dict | None = None,
    tool_config: dict | None = None,
) -> None:
    """Seeds everything a run_client_agent call needs end to end: tenant,
    vertical assignment, framework, template, and — only when a caller
    actually needs one, since produce_client_agent_instance reads the
    onboarding profile straight from Postgres rather than calling
    profile_tenant_fields — a fake-profiled onboarding profile. Pass
    `monkeypatch` only for a test that specifically checks per-client
    profile content; omit it for tests that just need a runnable client."""
    await _seed_tenant(hub_id)
    await set_tenant_vertical(hub_id, vertical)
    await _seed_framework(vertical)
    await _seed_template(vertical, tool_config=tool_config)
    if monkeypatch is not None:
        _fake_profiled(monkeypatch, profiled or {})
        await produce_onboarding_profile(hub_id, object_types=list((profiled or {}).keys()) or ["CONTACT"], allow_unqualified=True)


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
    """Stand-in for anthropic.AsyncAnthropic — same call shape
    (client.messages.create), scripted responses instead of a real call."""

    def __init__(self, responses):
        self.messages = _FakeMessages(responses)

    def __call__(self, *args, **kwargs):
        # Allows the same instance to be returned by the patched
        # AsyncAnthropic "constructor" regardless of the api_key passed.
        return self


def _one_pull_then_stop(object_type: str = "CONTACT"):
    """A scripted two-turn conversation: call pull_object_type once, then stop."""
    return [
        _FakeResponse(
            "tool_use",
            [_FakeToolUseBlock("call_1", "pull_object_type", {"object_type": object_type})],
        ),
        _FakeResponse("end_turn", [_FakeTextBlock("done")]),
    ]


def _list_then_pull_then_stop(object_type: str = "CONTACT"):
    """A scripted three-turn conversation exercising two distinct tool
    calls in the same run, so isolation across multiple mid-loop tool
    calls (not just one) is actually exercised."""
    return [
        _FakeResponse("tool_use", [_FakeToolUseBlock("call_1", "list_object_types", {})]),
        _FakeResponse(
            "tool_use",
            [_FakeToolUseBlock("call_2", "pull_object_type", {"object_type": object_type})],
        ),
        _FakeResponse("end_turn", [_FakeTextBlock("done")]),
    ]


def _patch_anthropic(monkeypatch, responses):
    fake = _FakeAsyncAnthropic(responses)
    monkeypatch.setattr(pull_agent, "AsyncAnthropic", fake)
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


# --- gathering only, never analysis ---


@pytest.mark.asyncio
async def test_output_shape_matches_pull_crm_objects_not_a_finding(monkeypatch):
    await _seed_client("hub_a", monkeypatch=monkeypatch)
    _patch_hubspot(monkeypatch)
    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    result = await run_client_agent("hub_a")

    # Checks the real pulled value, not just its shape — a garbled or
    # empty record would still satisfy isinstance(result["CONTACT"], list).
    assert result == {"CONTACT": [{"properties": {"hub_id_tag": "hub_a", "object_type": "CONTACT"}}]}
    # No diagnostic/finding-shaped keys ever appear in the output.
    assert "recommendations" not in result
    assert "priority" not in result


# --- restricted tool surface ---


@pytest.mark.asyncio
async def test_unknown_object_type_is_refused_before_touching_hubspot(monkeypatch):
    await _seed_client("hub_a", monkeypatch=monkeypatch)
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

    result = await run_client_agent("hub_a")

    assert result == {}
    assert pull_calls == []  # never reached HubSpot for the bogus type


# --- two-tier model: vertical template + client instance ---


@pytest.mark.asyncio
async def test_two_clients_of_the_same_vertical_share_the_template_but_hold_distinct_instances(monkeypatch):
    await _seed_tenant("hub_a")
    await _seed_tenant("hub_b")
    await set_tenant_vertical("hub_a", "saas")
    await set_tenant_vertical("hub_b", "saas")
    await _seed_framework("saas", content="SaaS framework v1")
    await _seed_template("saas", additions="Shared SaaS agent guidance")
    _patch_hubspot(monkeypatch)

    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))
    await run_client_agent("hub_a")

    # Re-patch per run since _FakeMessages.requests is per-instance
    fake = _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))
    await run_client_agent("hub_b")

    assert "SaaS framework v1" in fake.messages.requests[0]["system"]
    assert "Shared SaaS agent guidance" in fake.messages.requests[0]["system"]

    instance_a = await get_latest_client_agent_instance("hub_a")
    instance_b = await get_latest_client_agent_instance("hub_b")
    assert instance_a.vertical_template_id == instance_b.vertical_template_id
    assert instance_a.id != instance_b.id


@pytest.mark.asyncio
async def test_a_run_uses_the_tenants_persisted_instance_not_a_freshly_derived_one(monkeypatch):
    await _seed_client("hub_a", monkeypatch=monkeypatch)
    instance_id = await produce_client_agent_instance("hub_a")  # pre-produce, so a run must reuse it

    _patch_hubspot(monkeypatch)
    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))
    await run_client_agent("hub_a")

    latest = await get_latest_client_agent_instance("hub_a")
    # No new instance version was produced by the run itself.
    assert latest.id == instance_id


@pytest.mark.asyncio
async def test_a_run_with_no_existing_instance_produces_one_before_proceeding(monkeypatch):
    await _seed_client("hub_a")
    _patch_hubspot(monkeypatch)
    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    assert await get_latest_client_agent_instance("hub_a") is None

    await run_client_agent("hub_a")

    assert await get_latest_client_agent_instance("hub_a") is not None


# --- concurrent pulls for different tenants never cross-contaminate ---


@pytest.mark.asyncio
async def test_concurrent_runs_for_two_tenants_never_cross_contaminate(monkeypatch):
    await _seed_client("hub_a")
    await _seed_client("hub_b")
    await produce_client_agent_instance("hub_a")
    await produce_client_agent_instance("hub_b")
    _patch_hubspot(monkeypatch)

    # Each concurrent run needs its OWN fake Anthropic client instance
    # (a shared one would itself be an isolation bug this test should
    # catch) — patch a factory that returns a fresh fake per call.
    scripts = {"hub_a": _list_then_pull_then_stop("CONTACT"), "hub_b": _list_then_pull_then_stop("COMPANY")}
    call_index = {"n": 0}
    fakes = [_FakeAsyncAnthropic(scripts["hub_a"]), _FakeAsyncAnthropic(scripts["hub_b"])]

    def fake_constructor(*args, **kwargs):
        fake = fakes[call_index["n"]]
        call_index["n"] += 1
        return fake

    monkeypatch.setattr(pull_agent, "AsyncAnthropic", fake_constructor)

    result_a, result_b = await asyncio.gather(
        run_client_agent("hub_a"),
        run_client_agent("hub_b"),
    )

    assert set(result_a.keys()) == {"CONTACT"}
    assert result_a["CONTACT"][0]["properties"]["hub_id_tag"] == "hub_a"
    assert set(result_b.keys()) == {"COMPANY"}
    assert result_b["COMPANY"][0]["properties"]["hub_id_tag"] == "hub_b"


# --- every tool call mid-loop stays bound to the run's one tenant ---


@pytest.mark.asyncio
async def test_every_mid_loop_tool_call_stays_bound_to_the_runs_tenant(monkeypatch):
    await _seed_client("hub_a", monkeypatch=monkeypatch)
    constructed_hub_ids = []
    real_init = HubSpotDataPullClient.__init__

    def _recording_init(self, hub_id):
        constructed_hub_ids.append(hub_id)
        real_init(self, hub_id)

    monkeypatch.setattr(HubSpotDataPullClient, "__init__", _recording_init)
    _patch_hubspot(monkeypatch)
    _patch_anthropic(monkeypatch, _list_then_pull_then_stop("CONTACT"))

    await run_client_agent("hub_a")

    # Exactly one HubSpotDataPullClient constructed for the whole run,
    # regardless of how many tool calls happened inside it.
    assert constructed_hub_ids == ["hub_a"]


# --- a retried request rebuilds context fresh ---


@pytest.mark.asyncio
async def test_two_sequential_runs_for_the_same_tenant_dont_share_pull_state(monkeypatch):
    await _seed_client("hub_a", monkeypatch=monkeypatch)
    _patch_hubspot(monkeypatch)

    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))
    first = await run_client_agent("hub_a")

    _patch_anthropic(monkeypatch, _one_pull_then_stop("COMPANY"))
    second = await run_client_agent("hub_a")

    assert set(first.keys()) == {"CONTACT"}
    assert set(second.keys()) == {"COMPANY"}  # no leftover CONTACT from the first run


# --- every run is attributable to the correct tenant in the audit log ---


@pytest.mark.asyncio
async def test_successful_run_is_audited_under_the_correct_hub_id(monkeypatch):
    await _seed_client("hub_a", monkeypatch=monkeypatch)
    _patch_hubspot(monkeypatch)
    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    await run_client_agent("hub_a")

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT hub_id, event_type FROM audit_log WHERE event_type = 'pull_agent_run_completed'"
    )
    assert row["hub_id"] == "hub_a"


@pytest.mark.asyncio
async def test_failed_run_is_audited_under_the_correct_hub_id_and_reraises(monkeypatch):
    await _seed_client("hub_a", monkeypatch=monkeypatch)

    async def fake_pull_crm_objects(self, client=None, headers=None, object_types=None, properties=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(HubSpotDataPullClient, "pull_crm_objects", fake_pull_crm_objects)
    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    with pytest.raises(RuntimeError):
        await run_client_agent("hub_a")

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT hub_id, event_type FROM audit_log WHERE event_type = 'pull_agent_run_failed'"
    )
    assert row["hub_id"] == "hub_a"


@pytest.mark.asyncio
async def test_the_original_failure_survives_even_if_the_audit_write_also_fails(monkeypatch):
    # record_audit_best_effort catches its own failure and logs it rather
    # than propagating — a transient audit-log outage (plausibly the same
    # outage that caused the original failure) must not mask the real
    # RuntimeError with an unrelated one.
    await _seed_client("hub_a", monkeypatch=monkeypatch)

    async def fake_pull_crm_objects(self, client=None, headers=None, object_types=None, properties=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(HubSpotDataPullClient, "pull_crm_objects", fake_pull_crm_objects)
    _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    from auth import security

    async def failing_record_audit(*args, **kwargs):
        raise RuntimeError("audit_log insert failed")

    monkeypatch.setattr(security, "record_audit", failing_record_audit)

    with pytest.raises(RuntimeError, match="boom"):
        await run_client_agent("hub_a")


# --- the agent's tool-calling loop is bounded ---


@pytest.mark.asyncio
async def test_a_run_that_would_loop_past_the_budget_stops_gracefully(monkeypatch):
    await _seed_client("hub_a", monkeypatch=monkeypatch)
    _patch_hubspot(monkeypatch)

    # Scripts MAX_TOOL_CALLS + 5 tool_use turns in a row — the run must
    # stop at the budget rather than exhausting the whole script.
    over_budget_script = [
        _FakeResponse("tool_use", [_FakeToolUseBlock(f"call_{i}", "list_object_types", {})])
        for i in range(MAX_TOOL_CALLS + 5)
    ]
    fake = _patch_anthropic(monkeypatch, over_budget_script)

    result = await run_client_agent("hub_a")

    # The budget is enforced on the (MAX_TOOL_CALLS + 1)th tool call, one
    # request after the limit — checking the real call count, not just
    # that *some* dict came back, is what actually proves the loop
    # stopped rather than exhausting all MAX_TOOL_CALLS + 5 scripted turns.
    assert len(fake.messages.requests) == MAX_TOOL_CALLS + 1
    assert result == {}


@pytest.mark.asyncio
async def test_a_vertical_templates_tool_config_can_override_the_default_budget(monkeypatch):
    await _seed_client("hub_a", tool_config={"max_tool_calls": 2})

    over_budget_script = [
        _FakeResponse("tool_use", [_FakeToolUseBlock(f"call_{i}", "list_object_types", {})])
        for i in range(10)
    ]
    fake = _patch_anthropic(monkeypatch, over_budget_script)

    result = await run_client_agent("hub_a")

    # The vertical template's tool_config={"max_tool_calls": 2} override
    # is what should stop this at 3 requests (2 allowed + 1 that trips the
    # budget), not the module-level default of MAX_TOOL_CALLS — checking
    # the real count is what actually proves the override took effect.
    assert len(fake.messages.requests) == 3
    assert result == {}


# --- unresolvable vertical raises clearly rather than silently pulling nothing ---


@pytest.mark.asyncio
async def test_run_client_agent_raises_for_a_tenant_with_no_known_vertical():
    await _seed_tenant("hub_a")
    with pytest.raises(ValueError):
        await run_client_agent("hub_a")


# --- per-client context: the onboarding profile actually reaches the request ---


@pytest.mark.asyncio
async def test_client_with_no_onboarding_profile_still_runs(monkeypatch):
    await _seed_client("hub_a")
    _patch_hubspot(monkeypatch)
    fake = _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))

    await run_client_agent("hub_a")

    user_content = fake.messages.requests[0]["messages"][0]["content"]
    assert "No onboarding profile exists yet" in user_content


@pytest.mark.asyncio
async def test_two_clients_of_the_same_vertical_get_genuinely_different_requests(monkeypatch):
    # Deliberately different field names than test_client_agent.py's own
    # "distinctly scoped instances" test — this test proves something
    # that one can't: that the difference survives all the way into the
    # real outgoing Anthropic request, not just the stored instance.
    await _seed_tenant("hub_a")
    await _seed_tenant("hub_b")
    await set_tenant_vertical("hub_a", "saas")
    await set_tenant_vertical("hub_b", "saas")
    await _seed_framework("saas", content="Shared SaaS framework")
    await _seed_template("saas")

    _fake_profiled(
        monkeypatch,
        {"COMPANY": [FieldProfile("employee_count", True, 1, 1, "trust_by_default")]},
    )
    await produce_onboarding_profile("hub_a", object_types=["COMPANY"], allow_unqualified=True)

    _fake_profiled(
        monkeypatch,
        {"TICKET": [FieldProfile("priority_level", True, 1, 1, "unreliable_by_default")]},
    )
    await produce_onboarding_profile("hub_b", object_types=["TICKET"], allow_unqualified=True)

    _patch_hubspot(monkeypatch)
    fake_a = _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))
    await run_client_agent("hub_a")

    fake_b = _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))
    await run_client_agent("hub_b")

    content_a = fake_a.messages.requests[0]["messages"][0]["content"]
    content_b = fake_b.messages.requests[0]["messages"][0]["content"]

    # Same vertical, so the shared system prompt is identical...
    assert fake_a.messages.requests[0]["system"] == fake_b.messages.requests[0]["system"]
    # ...but the per-client user message genuinely differs.
    assert content_a != content_b
    assert "employee_count" in content_a
    assert "employee_count" not in content_b
    assert "priority_level" in content_b
    assert "priority_level" not in content_a


@pytest.mark.asyncio
async def test_a_clients_context_never_leaks_into_another_clients_request(monkeypatch):
    await _seed_tenant("hub_a")
    await _seed_tenant("hub_b")
    await set_tenant_vertical("hub_a", "saas")
    await set_tenant_vertical("hub_b", "saas")
    await _seed_framework("saas")
    await _seed_template("saas")

    _fake_profiled(
        monkeypatch,
        {"CONTACT": [FieldProfile("email", True, 1, 1, "trust_by_default")]},
    )
    await produce_onboarding_profile("hub_a", object_types=["CONTACT"], allow_unqualified=True)
    # hub_b deliberately has no onboarding profile at all.

    _patch_hubspot(monkeypatch)
    fake_b = _patch_anthropic(monkeypatch, _one_pull_then_stop("CONTACT"))
    await run_client_agent("hub_b")

    content_b = fake_b.messages.requests[0]["messages"][0]["content"]
    assert "email" not in content_b
    assert "No onboarding profile exists yet" in content_b
