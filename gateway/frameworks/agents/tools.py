"""Tool schemas and tool-dispatch for the agent hierarchy's gather phase
(openspec/changes/vertical-diagnostic-agent, per the gateway-package-layout
spec delta requiring tool schemas/dispatch to live separately from the
run-loop mechanics in `base.py`). Moved out of `base.py` unchanged —
pure relocation, no behavior change.

Every tool here wraps an already-allowlisted, already-tested
`HubSpotDataPullClient` method — this module gives the model no HubSpot
access path a human-written pull could not also reach (vertical-pull-agent's
"tool surface is limited to the existing allowlisted pull methods"
non-negotiable).
"""

import json
from typing import Awaitable, Callable

import httpx

from sync.hubspot_client import CRM_OBJECT_TYPES, HubSpotDataPullClient

TOOLS = [
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
    calls; caught in BaseAgent.run() to stop the loop and return whatever
    was gathered so far, rather than letting an agent loop or spend
    unboundedly."""


def bind_tool_executor(
    hs_client: HubSpotDataPullClient,
    confirmed_fields_for: Callable[[str], list[str] | None],
    http_client: httpx.AsyncClient | None,
    headers: dict | None,
    gathered: dict[str, list],
    max_tool_calls: int,
) -> Callable[[str, dict], Awaitable[str]]:
    """Returns a tool-execution closure bound to one agent run's own
    hs_client (itself already bound to exactly one hub_id at construction)
    — the model can never supply a hub_id, or reach any tenant's data
    besides the one this run was started for."""
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
            confirmed = confirmed_fields_for(object_type)
            if confirmed:
                properties_map = {object_type: confirmed}
            else:
                # Falls back to full live discovery — including every
                # real custom property this tenant's portal has for
                # the type — exactly as before this change, for any
                # object type nothing has been confirmed for yet.
                discovered = await hs_client.discover_object_properties(
                    object_type, client=http_client, headers=headers
                )
                properties_map = {object_type: discovered} if discovered else None
            pulled = await hs_client.pull_crm_objects(
                object_types=[object_type], properties=properties_map, client=http_client, headers=headers
            )
            records = pulled.get(object_type)
            if isinstance(records, list):
                gathered[object_type] = records
                return json.dumps({"pulled": len(records)})
            return json.dumps({"error": str(records)})

        if name == "list_custom_objects":
            schemas = await hs_client.discover_custom_object_schemas(client=http_client, headers=headers)
            return json.dumps(schemas)

        if name == "pull_custom_object":
            object_type_id = tool_input.get("object_type_id")
            confirmed = confirmed_fields_for(object_type_id)
            if confirmed:
                properties = confirmed
            else:
                definitions = await hs_client.discover_custom_object_properties(
                    object_type_id, client=http_client, headers=headers
                )
                properties = [d["name"] for d in definitions] or None
            result = await hs_client.pull_custom_object(
                object_type_id, client=http_client, headers=headers, properties=properties
            )
            if isinstance(result, list):
                gathered[object_type_id] = result
                return json.dumps({"pulled": len(result)})
            return json.dumps({"error": str(result)})

        return json.dumps({"error": f"unknown tool {name!r}"})

    return _execute
