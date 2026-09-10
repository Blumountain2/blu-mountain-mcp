"""The diagnostic phase (openspec/changes/vertical-diagnostic-agent): a
second, distinct step run after a client agent's gather phase completes,
reasoning over exactly that phase's already-gathered records against the
client's vertical framework, operational skill, and runtime prompt to
produce a real diagnostic narrative — the interpretation the gather phase
itself remains structurally forbidden from producing (vertical-pull-agent's
non-negotiable, scoped but otherwise unchanged by this module).

This phase has no HubSpot client of its own, no tool definitions that
reach HubSpot, and no code path to api.hubapi.com. It only ever reads the
gather phase's already-produced output, passed in by the caller — it
never re-gathers, re-pulls, or reaches back into HubSpot itself.

The framework/skill/prompt content itself is embedded as Python string
constants (openspec/changes/vertical-framework-content-in-code) — the
per-vertical `FRAMEWORK_TEXT` class attribute (`../verticals/*.py`) and
the shared `OPERATIONAL_SKILL_TEXT`/`RUNTIME_PROMPT_TEXT` constants
(`../content.py`) — rather than read from Postgres via
`frameworks.store.get_latest()` at request time, so a missing or
never-run ingestion step can no longer make a diagnostic run fail.
"""

import json

import structlog
from anthropic import AsyncAnthropic

from config import settings

from .content import OPERATIONAL_SKILL_TEXT, RUNTIME_PROMPT_TEXT

logger = structlog.get_logger()

MODEL = "claude-opus-5"

# A single output-shaping tool, not a HubSpot tool and not a loop: forcing
# the model to call this exactly once (tool_choice below) gives a reliable
# structured report instead of parsing free text, without giving the
# diagnosis phase any HubSpot access or letting it call anything more than
# once.
_REPORT_TOOL = {
    "name": "submit_diagnostic_report",
    "description": (
        "Submit the finished diagnostic report for this client. Call this "
        "exactly once, after reasoning over all of the gathered data below "
        "against the framework, operational skill, and prompt above."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "A prose health/risk assessment narrative for this client.",
            },
            "kpis": {
                "type": "array",
                "description": (
                    "The KPIs this vertical's framework calls for, computed from the "
                    "gathered data."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "value": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["name", "value"],
                    "additionalProperties": False,
                },
            },
            "risk_flags": {
                "type": "array",
                "description": "Specific risk or attention flags this vertical's framework surfaces.",
                "items": {"type": "string"},
            },
        },
        "required": ["summary", "kpis", "risk_flags"],
        "additionalProperties": False,
    },
}


class NoDiagnosticPromptContent(Exception):
    """Raised when the caller passed an empty framework_text — a real
    caller should never hit this (BaseAgent.__init__ already refuses to
    construct any agent with an empty FRAMEWORK_TEXT), but a direct
    caller of this function bypassing BaseAgent gets a clear error
    instead of silently reasoning over an empty framework section."""


def _diagnostic_system_prompt(vertical: str, framework_text: str, client_name: str, system_prompt_additions: str) -> str:
    if not framework_text:
        raise NoDiagnosticPromptContent(f"Empty framework_text passed for vertical {vertical!r}")

    # Targeted replace, not str.format(): the delivered prompt text is long
    # -form prose that may contain other literal "{...}" sequences (e.g.
    # examples) — a bare .format() would raise KeyError on those instead of
    # leaving them alone.
    rendered_prompt = RUNTIME_PROMPT_TEXT.replace("{CLIENT_NAME}", client_name).replace(
        "{VERTICAL_FRAMEWORK_NAME}", vertical
    )

    parts = [
        rendered_prompt,
        f"--- {vertical} operational skill ---\n{OPERATIONAL_SKILL_TEXT}",
        f"--- {vertical} framework ---\n{framework_text}",
    ]
    if system_prompt_additions:
        parts.append(f"--- {vertical} agent additions ---\n{system_prompt_additions}")
    return "\n\n".join(parts)


async def produce_diagnostic_report(
    vertical: str,
    framework_text: str,
    client_name: str,
    system_prompt_additions: str,
    gathered: dict[str, list],
) -> dict:
    """Runs the diagnostic phase once: a single, non-looping Claude call
    reasoning over `gathered` (this run's own gather-phase output, and
    nothing else) against `framework_text` plus the shared operational
    skill/runtime prompt constants. Returns {"summary": str, "kpis":
    [{"name", "value", "note"}, ...], "risk_flags": [str, ...]}."""
    system = _diagnostic_system_prompt(vertical, framework_text, client_name, system_prompt_additions)
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    response = await anthropic_client.messages.create(
        model=MODEL,
        # A real diagnostic report (Blu Mountain's own delivered template,
        # a comprehensive account diagnostic, not a two-sentence summary)
        # can genuinely need more than a small default output budget —
        # confirmed live: 4096 truncated mid-tool-call against a real
        # gathered dataset, producing a tool_use block with some or all
        # required fields silently missing rather than an error. 16384
        # gives real headroom; the stop_reason check below still catches
        # a genuine truncation rather than trusting a merely-large budget.
        max_tokens=16384,
        system=system,
        tools=[_REPORT_TOOL],
        tool_choice={"type": "tool", "name": "submit_diagnostic_report"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Here is the real HubSpot data gathered for this client, by object "
                    "type. Reason over it against the framework, operational skill, and "
                    "prompt above, then call submit_diagnostic_report exactly once.\n\n"
                    f"{json.dumps(gathered, default=str)}"
                ),
            }
        ],
    )

    if response.stop_reason == "max_tokens":
        logger.error(
            "frameworks.agents.diagnostics.truncated", vertical=vertical, max_tokens=16384
        )
        raise RuntimeError(
            "Diagnostic phase response was truncated (stop_reason=max_tokens) before "
            "submit_diagnostic_report could be completed — the report is not trustworthy "
            "and was discarded rather than returned partially filled."
        )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_diagnostic_report":
            report = dict(block.input)
            # "kpis": [] and "risk_flags": [] are legitimate (a genuinely
            # clean account has none to report) — only a field's outright
            # ABSENCE from the tool call, not an empty list/string value,
            # is treated as malformed output.
            missing = [key for key in ("summary", "kpis", "risk_flags") if key not in report]
            if missing:
                logger.error(
                    "frameworks.agents.diagnostics.incomplete_report", vertical=vertical, missing=missing
                )
                raise RuntimeError(f"submit_diagnostic_report was called with missing fields: {missing}")
            return report

    logger.error("frameworks.agents.diagnostics.no_report_submitted", vertical=vertical)
    raise RuntimeError("Diagnostic phase completed without calling submit_diagnostic_report")
