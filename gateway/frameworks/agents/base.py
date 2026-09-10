"""BaseAgent (openspec/changes/client-vertical-agent-classes): the
tool-calling loop mechanics shared by every vertical and every client
agent, unchanged in behavior from the prior DB-driven `run_client_agent`
— only *how* a vertical's/client's own configuration is supplied has
changed (real subclass attributes, not database rows).

`run()` (the gather phase) still only ever gathers data — never
interprets, diagnoses, or judges what it gathers; that guarantee is
unchanged and unloosened (vertical-pull-agent's non-negotiable, now
scoped explicitly to this phase). `diagnose()` (openspec/changes/
vertical-diagnostic-agent) is a distinct, separately-specified second
phase that MAY run after `run()` completes, consuming exactly that
phase's output to produce a real diagnostic narrative — see
`diagnostics.py`. It has no HubSpot client and no tool access of its
own; it never changes how the gather phase itself behaves.

Isolation is structural: `HUB_ID` is a class attribute a client subclass
sets once; the model can never supply or change which tenant a run
touches, no matter what it decides to call mid-loop.
"""

from contextlib import AsyncExitStack

import structlog
from anthropic import AsyncAnthropic

from auth.security import record_audit_best_effort
from config import settings
from sync.hubspot_client import HubSpotDataPullClient

from . import diagnostics
from .tools import TOOLS, ToolCallBudgetExceeded, bind_tool_executor

logger = structlog.get_logger()

MODEL = "claude-opus-5"

# Bounds a single run per specs/vertical-pull-agent/spec.md's "agent's
# tool-calling loop is bounded" requirement. 20 gives headroom for one
# list_object_types call plus one pull_object_type call per entry in
# CRM_OBJECT_TYPES (16 today), so a real run can check every object type
# in a single pass without hitting the cap.
MAX_TOOL_CALLS = 20


def _render_client_context(confirmed_fields: dict[str, list[str]]) -> str:
    """Renders a client's CONFIRMED_FIELDS into the same prose shape the
    prior onboarding-profile-derived injected_documentation used, so the
    model still sees which fields already matter for this client — just
    sourced from a class attribute now, not a database read."""
    if not confirmed_fields:
        return "No fields have been confirmed relevant for this client yet."
    lines = ["Fields already confirmed relevant for this client:"]
    for object_type, names in confirmed_fields.items():
        for name in names:
            lines.append(f"  - {object_type}.{name}")
    return "\n".join(lines)


class BaseAgent:
    """Subclassed once per vertical (setting VERTICAL/SYSTEM_PROMPT_ADDITIONS)
    and once more per client (additionally setting HUB_ID/CONFIRMED_FIELDS).
    Never instantiate this class or a bare vertical subclass directly —
    both are missing HUB_ID, and __init__ refuses to run without one."""

    VERTICAL: str = ""
    # Blu Mountain's own real, delivered vertical framework document,
    # embedded verbatim as a class attribute by each vertical subclass
    # (openspec/changes/vertical-framework-content-in-code) — no longer
    # read from Postgres at request time, so a missing/failed ingestion
    # step can never leave this empty at runtime.
    FRAMEWORK_TEXT: str = ""
    SYSTEM_PROMPT_ADDITIONS: str = ""
    MAX_TOOL_CALLS: int = MAX_TOOL_CALLS
    HUB_ID: str = ""
    # {object_type_or_custom_object_type_id: [property_name, ...]}. An
    # object type with no entry (or an empty list) falls back to full
    # live discovery — never narrower than what's explicitly confirmed,
    # never broader by accident.
    CONFIRMED_FIELDS: dict[str, list[str]] = {}
    # Optional friendly name for the diagnostic phase's {CLIENT_NAME}
    # prompt substitution (diagnostics.py). Falls back to HUB_ID when
    # unset — every existing client class predates this attribute and
    # none are required to set it.
    CLIENT_NAME: str = ""

    def __init__(self) -> None:
        if not self.HUB_ID:
            raise ValueError(
                f"{type(self).__name__} has no HUB_ID set — only a client class can be "
                "run, never a bare vertical class."
            )
        if not self.VERTICAL:
            raise ValueError(f"{type(self).__name__} has no VERTICAL set")
        if not self.FRAMEWORK_TEXT:
            raise ValueError(f"{type(self).__name__} has no FRAMEWORK_TEXT set")
        self.hub_id = self.HUB_ID
        self.hs_client = HubSpotDataPullClient(self.hub_id)

    def _confirmed_fields_for(self, object_type: str) -> list[str] | None:
        return self.CONFIRMED_FIELDS.get(object_type) or None

    async def _system_prompt(self) -> str:
        base = (
            f"You are a data-gathering assistant for a {self.VERTICAL} client's "
            "HubSpot portal. Your only job is deciding which HubSpot CRM object "
            "types are relevant to this vertical's analysis, based on the "
            "framework below, then pulling them with the pull_object_type tool "
            "(or, for a tenant-specific custom object, list_custom_objects then "
            "pull_custom_object). You gather raw data only — you never "
            "interpret, diagnose, or judge what the data means, and you never "
            "produce a recommendation or finding. Call list_object_types first "
            "if you need to see what's available, then call pull_object_type "
            "for each object type this vertical's framework indicates matters. "
            "Stop once you've pulled the relevant object types; do not pull "
            "object types the framework gives no indication are relevant to "
            f"{self.VERTICAL}. You only have access to HubSpot data. If the "
            "framework below mentions other sources (Slack, ClickUp, Harvest, "
            "Toggl, etc.), ignore those references — they are out of scope for "
            "this run and no tool exists to reach them.\n\n"
            f"--- {self.VERTICAL} framework ---\n{self.FRAMEWORK_TEXT}"
        )
        if self.SYSTEM_PROMPT_ADDITIONS:
            base += f"\n\n--- {self.VERTICAL} agent additions ---\n{self.SYSTEM_PROMPT_ADDITIONS}"
        return base

    async def run(self) -> dict[str, list]:
        """Runs this agent once. Returns gathered records in the same
        shape as HubSpotDataPullClient.pull_crm_objects: object_type (or
        a custom object's objectTypeId) -> list of raw records — never a
        diagnostic finding or recommendation."""
        max_tool_calls = self.MAX_TOOL_CALLS
        gathered: dict[str, list] = {}

        anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        system = await self._system_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    "Gather the HubSpot data relevant to this client's vertical, "
                    "then stop. Do not analyze or interpret anything you gather.\n\n"
                    f"--- this client ---\n{_render_client_context(self.CONFIRMED_FIELDS)}"
                ),
            }
        ]

        budget_exceeded = False
        # One shared connection for the whole run, mirroring pull_all()'s
        # and live_session.py's own connection-reuse pattern. Falls back
        # to per-call resolution (http_client=None) rather than failing
        # the whole run if the vault/connection can't be resolved upfront
        # — every tool call already handles client=None by resolving and
        # degrading individually.
        try:
            http_client, headers = await self.hs_client._client_for_hub()
        except Exception as exc:
            logger.warning("frameworks.agents.client_reuse_unavailable", hub_id=self.hub_id, error=str(exc))
            http_client, headers = None, None

        try:
            async with AsyncExitStack() as stack:
                if http_client is not None:
                    await stack.enter_async_context(http_client)
                execute_tool = bind_tool_executor(
                    self.hs_client, self._confirmed_fields_for, http_client, headers, gathered, max_tool_calls
                )
                while True:
                    response = await anthropic_client.messages.create(
                        model=MODEL,
                        max_tokens=4096,
                        system=system,
                        tools=TOOLS,
                        messages=messages,
                    )

                    if response.stop_reason != "tool_use":
                        break

                    messages.append({"role": "assistant", "content": response.content})
                    tool_results = []
                    for block in response.content:
                        if block.type != "tool_use":
                            continue
                        result = await execute_tool(block.name, block.input)
                        tool_results.append(
                            {"type": "tool_result", "tool_use_id": block.id, "content": result}
                        )
                    messages.append({"role": "user", "content": tool_results})
        except ToolCallBudgetExceeded:
            budget_exceeded = True
            logger.warning(
                "frameworks.agents.tool_call_budget_exceeded",
                hub_id=self.hub_id,
                vertical=self.VERTICAL,
                max_tool_calls=max_tool_calls,
            )
        except Exception as exc:
            logger.error("frameworks.agents.run_failed", hub_id=self.hub_id, vertical=self.VERTICAL, error=str(exc))
            # best-effort: a secondary audit-write failure here (e.g. the
            # same outage that caused the original failure) must not mask
            # the original exception with a new, unrelated one.
            await record_audit_best_effort(
                "pull_agent_run_failed", hub_id=self.hub_id, detail={"vertical": self.VERTICAL, "error": str(exc)}
            )
            raise

        logger.info(
            "frameworks.agents.run_completed",
            hub_id=self.hub_id,
            vertical=self.VERTICAL,
            agent_class=type(self).__name__,
            object_types_gathered=list(gathered.keys()),
            budget_exceeded=budget_exceeded,
        )
        # best-effort: the run itself already succeeded above; an
        # audit-log hiccup here shouldn't make a successful gather look
        # like a failure.
        await record_audit_best_effort(
            "pull_agent_run_completed",
            hub_id=self.hub_id,
            detail={
                "vertical": self.VERTICAL,
                "agent_class": type(self).__name__,
                "object_types_gathered": list(gathered.keys()),
                "budget_exceeded": budget_exceeded,
            },
        )
        return gathered

    async def diagnose(self, gathered: dict[str, list]) -> dict:
        """Runs the diagnostic phase (openspec/changes/vertical-diagnostic-
        agent) once, over exactly the records passed in — never re-gathers,
        never reaches HubSpot itself. `gathered` should ordinarily be this
        same instance's own `run()` output for the same tenant; nothing
        here re-validates that, so callers must not pass another tenant's
        gathered data.

        Returns a diagnostic report dict: {"summary": str, "kpis": [...],
        "risk_flags": [...]} — see diagnostics.produce_diagnostic_report."""
        try:
            report = await diagnostics.produce_diagnostic_report(
                vertical=self.VERTICAL,
                framework_text=self.FRAMEWORK_TEXT,
                client_name=self.CLIENT_NAME or self.HUB_ID,
                system_prompt_additions=self.SYSTEM_PROMPT_ADDITIONS,
                gathered=gathered,
            )
        except Exception as exc:
            logger.error(
                "frameworks.agents.diagnose_failed", hub_id=self.hub_id, vertical=self.VERTICAL, error=str(exc)
            )
            await record_audit_best_effort(
                "diagnostic_run_failed", hub_id=self.hub_id, detail={"vertical": self.VERTICAL, "error": str(exc)}
            )
            raise

        logger.info("frameworks.agents.diagnose_completed", hub_id=self.hub_id, vertical=self.VERTICAL)
        await record_audit_best_effort(
            "diagnostic_run_completed", hub_id=self.hub_id, detail={"vertical": self.VERTICAL}
        )
        return report
