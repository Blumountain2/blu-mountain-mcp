"""Tests for the diagnostic phase (openspec/changes/vertical-diagnostic-
agent): a distinct second step consuming a gather phase's own output to
produce a real interpretation, never re-gathering or reaching HubSpot
itself.

The Anthropic API itself is never called — a fake client scripts the
forced tool-call response, the same technique test_base.py already uses
for the gather phase. The shared operational-skill/runtime-prompt
constants (openspec/changes/vertical-framework-content-in-code) are
monkeypatched to short test strings rather than using the real ~20KB/~9KB
content, so tests stay fast and readable; framework_text is passed
directly per call, the same as a real BaseAgent.diagnose() would pass its
own FRAMEWORK_TEXT."""

import pytest

from frameworks.agents import diagnostics

_TEST_SKILL_TEXT = "Diagnose account health from the data given."
_TEST_PROMPT_TEXT = "Produce a report for {CLIENT_NAME}, a {VERTICAL_FRAMEWORK_NAME} client."
_TEST_FRAMEWORK_TEXT = "Trust hs_object_id. MRR is the headline KPI."


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, tool_id, name, tool_input):
        self.id = tool_id
        self.name = name
        self.input = tool_input


class _FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeResponse:
    def __init__(self, content, stop_reason="tool_use"):
        self.content = content
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return self._response


class _FakeAsyncAnthropic:
    def __init__(self, response):
        self.messages = _FakeMessages(response)

    def __call__(self, *args, **kwargs):
        return self


_REPORT = {
    "summary": "Healthy account, one risk on renewal timing.",
    "kpis": [{"name": "MRR", "value": "$12,000", "note": "one closed-won deal"}],
    "risk_flags": ["Renewal date within 30 days with no confirmed next step"],
}


def _patch_anthropic(monkeypatch, response):
    fake = _FakeAsyncAnthropic(response)
    monkeypatch.setattr(diagnostics, "AsyncAnthropic", fake)
    return fake


@pytest.fixture(autouse=True)
def _use_short_shared_content(monkeypatch):
    monkeypatch.setattr(diagnostics, "OPERATIONAL_SKILL_TEXT", _TEST_SKILL_TEXT)
    monkeypatch.setattr(diagnostics, "RUNTIME_PROMPT_TEXT", _TEST_PROMPT_TEXT)


async def _produce(monkeypatch=None, framework_text=_TEST_FRAMEWORK_TEXT, **overrides):
    kwargs = dict(
        vertical="saas",
        framework_text=framework_text,
        client_name="Acme Co",
        system_prompt_additions="",
        gathered={},
    )
    kwargs.update(overrides)
    return await diagnostics.produce_diagnostic_report(**kwargs)


@pytest.mark.asyncio
async def test_produce_diagnostic_report_returns_the_submitted_tool_input(monkeypatch):
    _patch_anthropic(
        monkeypatch,
        _FakeResponse([_FakeToolUseBlock("call_1", "submit_diagnostic_report", _REPORT)]),
    )

    report = await _produce(gathered={"DEAL": []})

    assert report == _REPORT
    # Never the gather phase's own raw-records shape.
    assert "DEAL" not in report


@pytest.mark.asyncio
async def test_client_name_and_vertical_are_substituted_into_the_rendered_prompt(monkeypatch):
    fake = _patch_anthropic(
        monkeypatch,
        _FakeResponse([_FakeToolUseBlock("call_1", "submit_diagnostic_report", _REPORT)]),
    )

    await _produce()

    system_prompt = fake.messages.requests[0]["system"]
    assert "Produce a report for Acme Co, a saas client." in system_prompt
    assert "{CLIENT_NAME}" not in system_prompt
    assert "{VERTICAL_FRAMEWORK_NAME}" not in system_prompt


@pytest.mark.asyncio
async def test_framework_text_reaches_the_system_prompt(monkeypatch):
    fake = _patch_anthropic(
        monkeypatch,
        _FakeResponse([_FakeToolUseBlock("call_1", "submit_diagnostic_report", _REPORT)]),
    )

    await _produce(framework_text="a distinctive real-framework marker string")

    assert "a distinctive real-framework marker string" in fake.messages.requests[0]["system"]


@pytest.mark.asyncio
async def test_the_diagnostic_phase_has_no_tool_access_to_hubspot(monkeypatch):
    fake = _patch_anthropic(
        monkeypatch,
        _FakeResponse([_FakeToolUseBlock("call_1", "submit_diagnostic_report", _REPORT)]),
    )

    await _produce()

    tool_names = {tool["name"] for tool in fake.messages.requests[0]["tools"]}
    assert tool_names == {"submit_diagnostic_report"}
    assert fake.messages.requests[0]["tool_choice"] == {"type": "tool", "name": "submit_diagnostic_report"}


@pytest.mark.asyncio
async def test_empty_framework_text_raises_clearly():
    # A real caller (BaseAgent) can never hit this — __init__ already
    # refuses to construct with an empty FRAMEWORK_TEXT — but a direct
    # caller of this function must still get a clear error, not silently
    # reason over an empty framework section.
    with pytest.raises(diagnostics.NoDiagnosticPromptContent, match="a-vertical-with-empty-framework-text"):
        await _produce(vertical="a-vertical-with-empty-framework-text", framework_text="")


@pytest.mark.asyncio
async def test_no_report_submitted_raises_runtime_error(monkeypatch):
    _patch_anthropic(monkeypatch, _FakeResponse([_FakeTextBlock("I didn't call the tool.")]))

    with pytest.raises(RuntimeError, match="submit_diagnostic_report"):
        await _produce()


@pytest.mark.asyncio
async def test_truncated_response_is_discarded_not_returned_partially_filled(monkeypatch):
    # Regression: confirmed live against a real portal that a truncated
    # tool call (stop_reason=max_tokens) can still produce a tool_use
    # block with some or all required fields silently missing — this must
    # raise clearly rather than returning that partial/empty report as if
    # it were a real one.
    _patch_anthropic(
        monkeypatch,
        _FakeResponse(
            [_FakeToolUseBlock("call_1", "submit_diagnostic_report", {"summary": "cut off mid-sen"})],
            stop_reason="max_tokens",
        ),
    )

    with pytest.raises(RuntimeError, match="truncated"):
        await _produce()


@pytest.mark.asyncio
async def test_a_report_missing_a_required_field_raises_clearly(monkeypatch):
    _patch_anthropic(
        monkeypatch,
        _FakeResponse(
            [_FakeToolUseBlock("call_1", "submit_diagnostic_report", {"summary": "ok", "kpis": []})],
        ),
    )

    with pytest.raises(RuntimeError, match="risk_flags"):
        await _produce()


@pytest.mark.asyncio
async def test_empty_kpis_and_risk_flags_are_legitimate_not_missing(monkeypatch):
    # A genuinely clean account has no KPIs or risk flags to report — an
    # empty list is a real, valid answer, not malformed output.
    clean_report = {"summary": "All clear.", "kpis": [], "risk_flags": []}
    _patch_anthropic(
        monkeypatch, _FakeResponse([_FakeToolUseBlock("call_1", "submit_diagnostic_report", clean_report)])
    )

    report = await _produce()

    assert report == clean_report


@pytest.mark.asyncio
async def test_gathered_data_reaches_the_user_message(monkeypatch):
    fake = _patch_anthropic(
        monkeypatch,
        _FakeResponse([_FakeToolUseBlock("call_1", "submit_diagnostic_report", _REPORT)]),
    )

    await _produce(gathered={"DEAL": [{"properties": {"amount": "12000"}}]})

    user_content = fake.messages.requests[0]["messages"][0]["content"]
    assert "12000" in user_content
