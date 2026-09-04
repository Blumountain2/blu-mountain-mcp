"""BaseAgent (openspec/changes/client-vertical-agent-classes): the
tool-calling loop mechanics shared by every vertical and every client
agent, unchanged in behavior from the prior DB-driven `run_client_agent`
— only *how* a vertical's/client's own configuration is supplied has
changed (real subclass attributes, not database rows). Gathers data
only — never interprets, diagnoses, or judges what the data means; that
stays the excluded analysis-job boundary (design.md's Non-Negotiables,
carried forward unchanged by this change).

Isolation is structural: `HUB_ID` is a class attribute a client subclass
sets once; the model can never supply or change which tenant a run
touches, no matter what it decides to call mid-loop.
"""

import json
from contextlib import AsyncExitStack

import httpx
import structlog
from anthropic import AsyncAnthropic

from auth.security import record_audit_best_effort
from config import settings
from sync.hubspot_client import CRM_OBJECT_TYPES, HubSpotDataPullClient

from ..store import CONTENT_TYPE_FRAMEWORK, get_latest

logger = structlog.get_logger()

MODEL = "claude-opus-5"

# Bounds a single run per specs/vertical-pull-agent/spec.md's "agent's
# tool-calling loop is bounded" requirement. 20 gives headroom for one
# list_object_types call plus one pull_object_type call per entry in
# CRM_OBJECT_TYPES (16 today), so a real run can check every object type
# in a single pass without hitting the cap.
MAX_TOOL_CALLS = 20

_TOOLS = [
    {
        "name": "list_object_types",
        "description": (
            "List every HubSpot CRM object type this tool surface can pull "
            "(e.g. CONTACT, COMPANY, DEAL)."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "pull_object_type",
        "description": (
            "Pull every real record of one HubSpot CRM object type for this "
            "run's tenant, via the existing allowlisted read-only pull path."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "object_type": {
                    "type": "string",
                    "enum": CRM_OBJECT_TYPES,
                    "description": "The CRM object type to pull.",
                }
            },
            "required": ["object_type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_custom_objects",
        "description": (
            "List this tenant's real custom object schemas (objectTypeId, name, "
            "labels), if any. Call this before pull_custom_object — a custom "
            "object's identifier is tenant-specific and can't be known ahead of "
            "discovering it here. Returns an empty list on a portal with no "
            "Custom Objects access, not an error."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "pull_custom_object",
        "description": (
            "Pull every real record of one of this tenant's custom objects, by "
            "the objectTypeId returned from list_custom_objects."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "object_type_id": {
                    "type": "string",
                    "description": "The objectTypeId returned by list_custom_objects.",
                }
            },
            "required": ["object_type_id"],
            "additionalProperties": False,
        },
    },
]


class ToolCallBudgetExceeded(Exception):
    """Raised internally when a run would exceed its configured max tool
    calls; caught in run() to stop the loop and return whatever was
    gathered so far, rather than letting an agent loop or spend
    unboundedly."""


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
    SYSTEM_PROMPT_ADDITIONS: str = ""
    MAX_TOOL_CALLS: int = MAX_TOOL_CALLS
    HUB_ID: str = ""
    # {object_type_or_custom_object_type_id: [property_name, ...]}. An
    # object type with no entry (or an empty list) falls back to full
    # live discovery — never narrower than what's explicitly confirmed,
    # never broader by accident.
    CONFIRMED_FIELDS: dict[str, list[str]] = {}

    def __init__(self) -> None:
        if not self.HUB_ID:
            raise ValueError(
                f"{type(self).__name__} has no HUB_ID set — only a client class can be "
                "run, never a bare vertical class."
            )
        if not self.VERTICAL:
            raise ValueError(f"{type(self).__name__} has no VERTICAL set")
        self.hub_id = self.HUB_ID
        self.hs_client = HubSpotDataPullClient(self.hub_id)

    def _confirmed_fields_for(self, object_type: str) -> list[str] | None:
        return self.CONFIRMED_FIELDS.get(object_type) or None

    async def _system_prompt(self) -> str:
        framework = await get_latest(CONTENT_TYPE_FRAMEWORK, self.VERTICAL)
        if framework is None:
            raise ValueError(f"No stored framework for vertical {self.VERTICAL!r}")
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
            f"--- {self.VERTICAL} framework ---\n{framework.content}"
        )
        if self.SYSTEM_PROMPT_ADDITIONS:
            base += f"\n\n--- {self.VERTICAL} agent additions ---\n{self.SYSTEM_PROMPT_ADDITIONS}"
        return base

    def _bind_tool_executor(
        self,
        http_client: httpx.AsyncClient | None,
        headers: dict | None,
        gathered: dict[str, list],
        max_tool_calls: int,
    ):
        """Returns a tool-execution closure bound to this instance's own
        hs_client (itself already bound to exactly one hub_id at
        construction) — the model can never supply a hub_id, or reach any
        tenant's data besides the one this agent was constructed for."""
        call_count = 0

        async def _execute(name: str, tool_input: dict) -> str:
            nonlocal call_count
            call_count += 1
            if call_count > max_tool_calls:
                raise ToolCallBudgetExceeded()

            if name == "list_object_types":
                return json.dumps(CRM_OBJECT_TYPES)

            if name == "pull_object_type":
                object_type = tool_input.get("object_type")
                if object_type not in CRM_OBJECT_TYPES:
                    return json.dumps({"error": f"unknown object_type {object_type!r}"})
                confirmed = self._confirmed_fields_for(object_type)
                if confirmed:
                    properties_map = {object_type: confirmed}
                else:
                    # Falls back to full live discovery — including every
                    # real custom property this tenant's portal has for
                    # the type — exactly as before this change, for any
                    # object type nothing has been confirmed for yet.
                    discovered = await self.hs_client.discover_object_properties(
                        object_type, client=http_client, headers=headers
                    )
                    properties_map = {object_type: discovered} if discovered else None
                pulled = await self.hs_client.pull_crm_objects(
                    object_types=[object_type], properties=properties_map, client=http_client, headers=headers
                )
                records = pulled.get(object_type)
                if isinstance(records, list):
                    gathered[object_type] = records
                    return json.dumps({"pulled": len(records)})
                return json.dumps({"error": str(records)})

            if name == "list_custom_objects":
                schemas = await self.hs_client.discover_custom_object_schemas(
                    client=http_client, headers=headers
                )
                return json.dumps(schemas)

            if name == "pull_custom_object":
                object_type_id = tool_input.get("object_type_id")
                confirmed = self._confirmed_fields_for(object_type_id)
                if confirmed:
                    properties = confirmed
                else:
                    definitions = await self.hs_client.discover_custom_object_properties(
                        object_type_id, client=http_client, headers=headers
                    )
                    properties = [d["name"] for d in definitions] or None
                result = await self.hs_client.pull_custom_object(
                    object_type_id, client=http_client, headers=headers, properties=properties
                )
                if isinstance(result, list):
                    gathered[object_type_id] = result
                    return json.dumps({"pulled": len(result)})
                return json.dumps({"error": str(result)})

            return json.dumps({"error": f"unknown tool {name!r}"})

        return _execute

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
                execute_tool = self._bind_tool_executor(http_client, headers, gathered, max_tool_calls)
                while True:
                    response = await anthropic_client.messages.create(
                        model=MODEL,
                        max_tokens=4096,
                        system=system,
                        tools=_TOOLS,
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
