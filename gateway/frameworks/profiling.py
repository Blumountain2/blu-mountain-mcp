"""Tenant field profiling (task 2, specs/tenant-field-profiling/spec.md):
discovers which of a tenant's real HubSpot fields are actually populated
and in active use, informed by that tenant's known vertical framework's
own default-trust/default-unreliable property guidance where available.

Reuses sync.hubspot_client.HubSpotDataPullClient.pull_crm_objects() — the
same, already-allowlisted read path everything else in this project pulls
CRM objects through — no new HubSpot access path. HubSpotDataPullClient is
constructed fresh per call, scoped to exactly one hub_id's vaulted token,
the same isolation-by-construction pattern used everywhere else in this
project.
"""

import asyncio
from dataclasses import dataclass

import httpx
import structlog

from sync.hubspot_client import HubSpotDataPullClient

from .guidance import FRAMEWORK_PROPERTY_GUIDANCE

logger = structlog.get_logger()

_TRUST = "trust_by_default"
_UNRELIABLE = "unreliable_by_default"


@dataclass(frozen=True)
class FieldProfile:
    """One property's profile within one object type, for one tenant."""

    name: str
    populated: bool
    populated_count: int
    total_records: int
    framework_guidance: str | None  # "trust_by_default" | "unreliable_by_default" | None
    is_custom: bool = False  # HubSpot's own hubspotDefined flag, negated — see discover_object_property_definitions


def _profile_object_type(records: list, guidance: dict | None, custom_by_name: dict[str, bool]) -> list[FieldProfile]:
    populated_counts: dict[str, int] = {}
    all_names: set[str] = set()

    for record in records:
        properties = record.get("properties") if isinstance(record, dict) else None
        if not isinstance(properties, dict):
            continue
        for name, value in properties.items():
            all_names.add(name)
            # A populated value is non-None and non-blank once stringified
            # — HubSpot returns "" for some genuinely-empty text properties
            # rather than omitting the key entirely.
            if value is not None and str(value).strip() != "":
                populated_counts[name] = populated_counts.get(name, 0) + 1

    total = len(records)
    trust_list = guidance.get(_TRUST, []) if guidance else []
    unreliable_list = guidance.get(_UNRELIABLE, []) if guidance else []

    profiles = []
    for name in sorted(all_names):
        populated_count = populated_counts.get(name, 0)
        if name in trust_list:
            framework_guidance = _TRUST
        elif name in unreliable_list:
            framework_guidance = _UNRELIABLE
        else:
            framework_guidance = None
        profiles.append(
            FieldProfile(
                name=name,
                populated=populated_count > 0,
                populated_count=populated_count,
                total_records=total,
                framework_guidance=framework_guidance,
                is_custom=custom_by_name.get(name, False),
            )
        )
    return profiles


async def profile_tenant_fields(
    hub_id: str,
    object_types: list[str],
    vertical: str | None = None,
) -> dict[str, list[FieldProfile]]:
    """Profiles which properties are actually populated, per object type,
    for exactly one tenant. If `vertical` is given and guidance is known
    for it, each property is cross-referenced against that vertical's
    trust_by_default/unreliable_by_default lists; if not — including when
    the vertical simply isn't known yet for this tenant — profiling still
    runs, just without that cross-reference (specs/tenant-field-profiling
    /spec.md: "Profiling MAY still run, producing an unqualified result,
    when no vertical is yet known for a tenant")."""
    client = HubSpotDataPullClient(hub_id)

    async def _discover(
        object_type: str, http_client: httpx.AsyncClient, headers: dict
    ) -> tuple[str, list[str], dict[str, bool]]:
        # Discovers each object type's full property set first (task
        # 5.2/5.4, openspec/changes/separate-vertical-client-agents) via
        # discover_object_property_definitions, then pulls with those
        # explicit columns. Without this, the underlying REST pull would
        # only ever see HubSpot's own small default property set, never a
        # portal's custom properties, so no custom field could ever be
        # profiled or marked is_custom in the first place. A discovery
        # failure for one object type degrades to the default pull for
        # that type alone, rather than failing the whole run.
        #
        # hubspotDefined (task 3.4, openspec/changes/hubspot-rest-api-pivot)
        # is REST's own authoritative custom/standard flag, replacing the
        # prior is_custom_property_name() heuristic — every property this
        # project marks is_custom now matches HubSpot's own record for it.
        #
        # discover_object_property_definitions's real implementation
        # already degrades to [] internally and never raises — but this
        # try/except is kept anyway as defense-in-depth against that
        # contract ever being violated (a future edit, or a test double
        # that doesn't honor it), matching this function's own promise
        # that one object type's failure never fails the whole run.
        try:
            definitions = await client.discover_object_property_definitions(
                object_type, client=http_client, headers=headers
            )
        except Exception as exc:
            client.log_pull_failure(f"properties:{object_type}", exc)
            definitions = []
        names = [d["name"] for d in definitions]
        custom_by_name = {d["name"]: not d["hubspotDefined"] for d in definitions}
        return object_type, names, custom_by_name

    # One shared connection for the whole profiling run, mirroring
    # pull_all()'s and live_session.py's own connection-reuse pattern —
    # without this, profiling M object types opened M+1 separate
    # httpx.AsyncClients and made M+1 separate vault token lookups.
    http_client, headers = await client._client_for_hub()
    async with http_client:
        discovery_results = await asyncio.gather(
            *(_discover(t, http_client, headers) for t in object_types)
        )
        discovered = {object_type: names for object_type, names, _custom in discovery_results}
        custom_by_type = {object_type: custom for object_type, _names, custom in discovery_results}
        pulled = await client.pull_crm_objects(
            object_types=object_types, properties=discovered, client=http_client, headers=headers
        )

    guidance = FRAMEWORK_PROPERTY_GUIDANCE.get(vertical) if vertical else None
    if vertical and guidance is None:
        logger.warning("frameworks.profiling.no_guidance_for_vertical", hub_id=hub_id, vertical=vertical)

    result: dict[str, list[FieldProfile]] = {}
    for object_type, records in pulled.items():
        if not isinstance(records, list):
            # {"error": "pull_failed"} or similar — nothing to profile for
            # this object type on this tenant/portal; not this function's
            # job to retry or paper over, the pull layer already logged it.
            continue
        result[object_type] = _profile_object_type(records, guidance, custom_by_type.get(object_type, {}))

    logger.info(
        "frameworks.profiling.completed",
        hub_id=hub_id,
        object_types=list(result.keys()),
        vertical=vertical,
    )
    return result
