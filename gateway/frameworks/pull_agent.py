"""Vertical pull agent (task 8, specs/vertical-pull-agent/spec.md; rewired
by openspec/changes/separate-vertical-client-agents to the two-tier
template/instance model below): a Claude API tool-use agent that decides
which of the existing allowlisted HubSpot pull methods to call to gather
one client's relevant data. Gathers data only — it never interprets,
diagnoses, or judges what the data means; that stays the excluded
analysis-job boundary (design.md's Non-Negotiables). No fine-tuning or
training is involved anywhere in this module — confirmed via research
(analysis-model-templates/design.md's Decisions) that no such path fits
this project.

**Two-tier model (openspec/changes/separate-vertical-client-agents),
superseding the prior "one shared agent config per vertical, no per-client
persistence" design**: `run_client_agent(hub_id)` resolves hub_id's
persisted `client_agent.ClientAgentInstance` (producing one if absent) and
that instance's referenced `vertical_templates.VerticalAgentTemplate`,
then builds its system prompt from the vertical's raw framework text
(`analysis_content`, still shared and unmodified) plus that template's own
system-prompt additions (this project's own configuration, independently
editable per vertical). The user message is the instance's own persisted
`injected_documentation` — a rendered snapshot taken when the instance was
produced, not recomputed live on every run. Two clients of the same
vertical share the same template but hold genuinely different instances.

Isolation is structural, not conventional: `hub_id` is bound into the
tool-execution closure in `run_client_agent` once, at the start of a run,
and never accepted as a tool parameter the model could supply — a run
started for one tenant cannot be made to call another tenant's HubSpot
connection no matter what the model decides to do mid-loop.
"""

import json
from contextlib import AsyncExitStack

import httpx
import structlog
from anthropic import AsyncAnthropic

from auth.security import record_audit_best_effort
from config import settings
from sync.hubspot_client import CRM_OBJECT_TYPES, HubSpotDataPullClient

from .client_agent import resolve_client_agent_instance, resolve_template_for_instance
from .store import CONTENT_TYPE_FRAMEWORK, get_latest
from .vertical_templates import VerticalAgentTemplate

logger = structlog.get_logger()

MODEL = "claude-opus-5"

# Bounds a single run per specs/vertical-pull-agent/spec.md's "agent's
# tool-calling loop is bounded" requirement — an agent that decides what
# to call, unlike every other fixed pull path in this project, could in
# principle loop or spend unboundedly without this. 20 gives headroom for
# one list_object_types call plus one pull_object_type call per entry in
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
]


class ToolCallBudgetExceeded(Exception):
    """Raised internally when a run would exceed its configured max tool
    calls; caught in run_client_agent to stop the loop and return whatever
    was gathered so far, rather than letting an agent loop or spend
    unboundedly."""


def _system_prompt(vertical: str, framework_content: str, template_additions: str) -> str:
    base = (
        f"You are a data-gathering assistant for a {vertical} client's HubSpot "
        "portal. Your only job is deciding which HubSpot CRM object types are "
        "relevant to this vertical's analysis, based on the framework below, "
        "then pulling them with the pull_object_type tool. You gather raw data "
        "only — you never interpret, diagnose, or judge what the data means, "
        "and you never produce a recommendation or finding. Call "
        "list_object_types first if you need to see what's available, then "
        "call pull_object_type for each object type this vertical's framework "
        "indicates matters. Stop once you've pulled the relevant object types; "
        "do not pull object types the framework gives no indication are "
        f"relevant to {vertical}. You only have access to HubSpot data. If "
        "the framework below mentions other sources (Slack, ClickUp, "
        "Harvest, Toggl, etc.), ignore those references — they are out of "
        "scope for this run and no tool exists to reach them.\n\n"
        f"--- {vertical} framework ---\n{framework_content}"
    )
    if template_additions:
        # This vertical's own agent-template additions (tool-use guidance,
        # prioritization, style) — this project's own configuration,
        # independently editable per vertical, layered after Blu
        # Mountain's raw framework text rather than mixed into it.
        base += f"\n\n--- {vertical} agent template additions ---\n{template_additions}"
    return base


def _bind_tool_executor(
    hs_client: HubSpotDataPullClient,
    http_client: httpx.AsyncClient | None,
    headers: dict | None,
    gathered: dict[str, list],
    max_tool_calls: int,
):
    """Returns a tool-execution closure bound to exactly one
    HubSpotDataPullClient instance (itself already bound to one hub_id at
    construction) — the model can never supply a hub_id, or reach any
    tenant's data besides the one this closure was built for.

    http_client/headers are resolved once by the caller and threaded
    through every tool call, mirroring pull_all()'s and live_session.py's
    own single-connection-per-run pattern — without this, a full run over
    every CRM_OBJECT_TYPES entry opened a separate httpx.AsyncClient and
    made a separate vault token lookup for each of the two HubSpot calls
    per pull_object_type invocation."""
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
            # Discovers every real property this tenant's portal has for
            # the type first (including custom ones) and requests all of
            # them explicitly, rather than letting pull_crm_objects fall
            # through to HubSpot's small default set. Without this, no
            # custom property (health score, MRR, plan tier, delivery
            # status, project fields, etc.) ever reached a gathered
            # record — confirmed against this project's own vertical
            # framework documentation that every vertical's Tier 2/3
            # metrics depend on exactly this kind of field. Returns []
            # harmlessly for the four non-standard object types (CAMPAIGN,
            # LANDING_PAGE, BLOG_POST, OBJECT_LIST), which fall back to
            # pull_crm_objects's own default handling for those.
            discovered_properties = await hs_client.discover_object_properties(
                object_type, client=http_client, headers=headers
            )
            properties_map = {object_type: discovered_properties} if discovered_properties else None
            pulled = await hs_client.pull_crm_objects(
                object_types=[object_type], properties=properties_map, client=http_client, headers=headers
            )
            records = pulled.get(object_type)
            if isinstance(records, list):
                gathered[object_type] = records
                return json.dumps({"pulled": len(records)})
            return json.dumps({"error": str(records)})

        return json.dumps({"error": f"unknown tool {name!r}"})

    return _execute


async def run_client_agent(
    hub_id: str,
    vertical: str | None = None,
    allow_unqualified: bool = False,
) -> dict[str, list]:
    """Runs the pull agent for exactly one client, resolving its persisted
    `client_agent.ClientAgentInstance` first (producing one if absent) and
    that instance's referenced `vertical_templates.VerticalAgentTemplate` —
    the two-tier model that superseded the prior single ephemeral
    per-vertical config (see this module's docstring). Returns gathered
    records in the same shape as HubSpotDataPullClient.pull_crm_objects:
    object_type -> list of raw records — never a diagnostic finding or
    recommendation (specs/vertical-pull-agent/spec.md).

    `vertical`/`allow_unqualified` are forwarded to instance resolution
    only when no instance exists yet for hub_id — an already-produced
    instance's own vertical always wins, since the instance is the
    durable record of which vertical this client's agent was built
    against."""
    instance = await resolve_client_agent_instance(hub_id, vertical=vertical, allow_unqualified=allow_unqualified)
    template: VerticalAgentTemplate = await resolve_template_for_instance(instance)
    resolved_vertical = template.vertical

    framework = await get_latest(CONTENT_TYPE_FRAMEWORK, resolved_vertical)
    if framework is None:
        raise ValueError(f"No stored framework for vertical {resolved_vertical!r}")

    max_tool_calls = template.tool_config.get("max_tool_calls", MAX_TOOL_CALLS)

    hs_client = HubSpotDataPullClient(hub_id)
    gathered: dict[str, list] = {}

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    system = _system_prompt(resolved_vertical, framework.content, template.system_prompt_additions)
    messages = [
        {
            "role": "user",
            "content": (
                "Gather the HubSpot data relevant to this client's vertical, "
                "then stop. Do not analyze or interpret anything you gather.\n\n"
                f"--- this client ---\n{instance.injected_documentation}"
            ),
        }
    ]

    budget_exceeded = False
    # One shared connection for the whole run, mirroring pull_all()'s and
    # live_session.py's own connection-reuse pattern — without this,
    # every pull_object_type tool call opened its own httpx.AsyncClient
    # and made its own vault token lookup. Falls back to per-call
    # resolution (http_client=None, exactly today's behavior) rather than
    # failing the whole run if the vault/connection can't be resolved
    # upfront — discover_object_properties/pull_crm_objects already
    # handle client=None by resolving and degrading individually.
    try:
        http_client, headers = await hs_client._client_for_hub()
    except Exception as exc:
        logger.warning("frameworks.pull_agent.client_reuse_unavailable", hub_id=hub_id, error=str(exc))
        http_client, headers = None, None

    try:
        async with AsyncExitStack() as stack:
            if http_client is not None:
                await stack.enter_async_context(http_client)
            execute_tool = _bind_tool_executor(hs_client, http_client, headers, gathered, max_tool_calls)
            while True:
                response = await client.messages.create(
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
            "frameworks.pull_agent.tool_call_budget_exceeded",
            hub_id=hub_id,
            vertical=resolved_vertical,
            max_tool_calls=max_tool_calls,
        )
    except Exception as exc:
        logger.error("frameworks.pull_agent.run_failed", hub_id=hub_id, vertical=resolved_vertical, error=str(exc))
        # best-effort: a secondary audit-write failure here (e.g. the same
        # outage that caused the original failure) must not mask the
        # original exception with a new, unrelated one.
        await record_audit_best_effort(
            "pull_agent_run_failed", hub_id=hub_id, detail={"vertical": resolved_vertical, "error": str(exc)}
        )
        raise

    logger.info(
        "frameworks.pull_agent.run_completed",
        hub_id=hub_id,
        vertical=resolved_vertical,
        client_agent_instance_id=instance.id,
        vertical_template_version=template.version,
        object_types_gathered=list(gathered.keys()),
        budget_exceeded=budget_exceeded,
    )
    # best-effort: the run itself already succeeded above; an audit-log
    # hiccup here shouldn't make a successful gather look like a failure.
    await record_audit_best_effort(
        "pull_agent_run_completed",
        hub_id=hub_id,
        detail={
            "vertical": resolved_vertical,
            "client_agent_instance_id": instance.id,
            "vertical_template_version": template.version,
            "object_types_gathered": list(gathered.keys()),
            "budget_exceeded": budget_exceeded,
        },
    )
    return gathered
