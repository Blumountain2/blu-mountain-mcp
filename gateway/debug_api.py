"""A plain HTTP API for pulling a real installed tenant's HubSpot data
directly, for manual testing via Postman rather than through the MCP
protocol (which Postman can't represent naturally — see the live
session's /mcp mount).

Gated shut by default (config.settings.debug_api_key): every request
needs X-Debug-Api-Key to match it exactly, checked before touching
Postgres or HubSpot. An empty configured key means every request 401s,
fail-closed — the same posture as an empty FASTMCP_ALLOWED_GOOGLE_DOMAINS.
Every successful pull is still recorded in audit_log (staff_identity=None,
distinguishing it from a live-session staff read), the same discipline
the rest of this project applies to every other HubSpot access path.

Read-only, same as every other HubSpot access path in this project — this
router only ever calls HubSpotDataPullClient's existing, already-allowlisted
read methods, never a new access mechanism of its own.
"""

from fastapi import APIRouter, Header, HTTPException

from auth import TENANT_DISPLAY_NAME_SQL, get_installed_hub_ids, record_audit
from config import settings
from db import get_pool
from sync.hubspot_client import (
    CRM_OBJECT_TYPES,
    HubSpotDataPullClient,
    ReadOnlyViolation,
    resolve_object_type_aliases,
)

router = APIRouter(prefix="/debug/hubspot", tags=["debug"])


def _require_api_key(x_debug_api_key: str | None) -> None:
    if not settings.debug_api_key or x_debug_api_key != settings.debug_api_key:
        raise HTTPException(401, "Missing or invalid X-Debug-Api-Key")


def _resolve_object_type(object_type: str) -> str:
    """Accepts either the exact CRM_OBJECT_TYPES name (any casing) or any
    of its free-text aliases (e.g. "contacts", "line items") — the same
    shared resolver session/live_session.py's query tools use, so a
    Postman caller doesn't need to know the exact ALL_CAPS/singular
    constant names (CONTACT, MEETING_EVENT, etc.) to use this API."""
    matches = resolve_object_type_aliases(object_type)
    if not matches:
        raise HTTPException(400, f"Unknown object_type {object_type!r}; see GET /debug/hubspot/object-types")
    return matches[0]


def _parse_properties_param(properties: str | None) -> list[str] | None:
    """Parses the `?properties=a,b,c` query param shared by every route
    here that narrows a pull to specific fields — blank entries dropped.
    Returns `None` only when `properties` itself is `None`/empty (matches
    each call site's prior inline behavior exactly, including the edge
    case of an all-blank value like "," or ",,," returning `[]`, not
    `None` — that distinction doesn't change pull behavior downstream
    (both are falsy to `properties or []`) but does change what value
    lands in the audit log's own recorded detail, so it's preserved)."""
    if not properties:
        return None
    return [p.strip() for p in properties.split(",") if p.strip()]


async def _require_installed_tenant(hub_id: str) -> None:
    """404s for any hub_id that isn't a real, currently-installed tenant —
    this is the actual per-request scoping (not a hardcoded test-hub_id
    allowlist): only real installs are ever reachable, by construction,
    the same way every other caller of HubSpotDataPullClient is scoped.
    Checked against `get_installed_hub_ids()` — this project's single
    source of truth for "which tenants are active," already shared by
    the scheduled sync and the live session, so this becomes a third
    consumer of the same predicate instead of a fourth hand-written copy
    of it."""
    if hub_id not in await get_installed_hub_ids():
        raise HTTPException(404, f"{hub_id!r} is not a currently-installed tenant")


@router.get("/tenants")
async def list_tenants(x_debug_api_key: str | None = Header(default=None)) -> list[dict]:
    """Every currently-installed tenant, with its display name — the
    starting point for picking a hub_id to use in every other endpoint
    below. Same shared name-fallback chain as the live session's own
    list_my_tenants (`auth.TENANT_DISPLAY_NAME_SQL`)."""
    _require_api_key(x_debug_api_key)
    pool = await get_pool()
    rows = await pool.fetch(
        f"""
        SELECT hub_id,
               {TENANT_DISPLAY_NAME_SQL} AS name
        FROM tenants
        WHERE install_status = 'installed'
        ORDER BY hub_id
        """
    )
    return [{"hub_id": row["hub_id"], "name": row["name"]} for row in rows]


@router.get("/object-types")
async def list_object_types(x_debug_api_key: str | None = Header(default=None)) -> dict:
    """The fixed set of CRM object types and generic capabilities this
    project's pull client actually supports — so a Postman user knows
    what's a valid {object_type}/{capability} path segment below without
    reading the source."""
    _require_api_key(x_debug_api_key)
    return {
        "crm_object_types": CRM_OBJECT_TYPES,
        "capabilities": await HubSpotDataPullClient.list_read_only_tools(),
    }


@router.get("/{hub_id}/crm/{object_type}")
async def pull_crm_object_type(
    hub_id: str,
    object_type: str,
    properties: str | None = None,
    x_debug_api_key: str | None = Header(default=None),
) -> dict:
    """Pulls one CRM object type (contacts, companies, deals, etc. — see
    GET /object-types for the full list) for one real installed tenant.
    `properties` is an optional comma-separated list of exact HubSpot
    property names to narrow the response to (REST's properties= is
    exclusive, not additive — see CLAUDE.md's Data pull section)."""
    _require_api_key(x_debug_api_key)
    await _require_installed_tenant(hub_id)
    normalized_type = _resolve_object_type(object_type)

    requested_properties = _parse_properties_param(properties)
    properties_map = {normalized_type: requested_properties} if requested_properties else None

    client = HubSpotDataPullClient(hub_id)
    result = await client.pull_crm_objects(object_types=[normalized_type], properties=properties_map)
    await record_audit(
        "debug_api_pull", hub_id=hub_id, detail={"object_type": normalized_type, "properties": requested_properties}
    )
    return {normalized_type: result.get(normalized_type)}


@router.get("/{hub_id}/properties/{object_type}")
async def pull_object_properties(
    hub_id: str, object_type: str, x_debug_api_key: str | None = Header(default=None)
) -> dict:
    """Every real property HubSpot has for one CRM object type on this
    tenant's portal, including custom ones, with the authoritative
    hubspotDefined flag — GET /crm/v3/properties/{type} under the hood."""
    _require_api_key(x_debug_api_key)
    await _require_installed_tenant(hub_id)
    normalized_type = _resolve_object_type(object_type)

    client = HubSpotDataPullClient(hub_id)
    definitions = await client.discover_object_property_definitions(normalized_type)
    await record_audit("debug_api_properties", hub_id=hub_id, detail={"object_type": normalized_type})
    return {"object_type": normalized_type, "properties": definitions}


@router.get("/{hub_id}/capability/{capability_name}")
async def pull_capability(
    hub_id: str, capability_name: str, x_debug_api_key: str | None = Header(default=None)
) -> dict:
    """One of the five generic capabilities (owners, organization_details,
    content_analytics, marketing_email_analytics, campaign_attribution —
    see GET /debug/hubspot/object-types) for one real installed tenant."""
    _require_api_key(x_debug_api_key)
    await _require_installed_tenant(hub_id)

    client = HubSpotDataPullClient(hub_id)
    try:
        result = await client.pull_object(capability_name)
    except ReadOnlyViolation as exc:
        raise HTTPException(400, str(exc)) from exc
    await record_audit("debug_api_capability", hub_id=hub_id, detail={"capability": capability_name})
    return {capability_name: result}


@router.get("/{hub_id}/custom-objects")
async def list_custom_objects(hub_id: str, x_debug_api_key: str | None = Header(default=None)) -> dict:
    """Every custom object schema defined on this tenant's real portal —
    discovered fresh, at call time; there's no fixed list of these the
    way there is for standard CRM object types (openspec/changes/
    custom-object-support). Each result's `objectTypeId` is what
    GET /{hub_id}/custom-objects/{object_type_id} below needs. Empty,
    not an error, on a portal without Custom Objects access (an
    Enterprise-tier HubSpot feature)."""
    _require_api_key(x_debug_api_key)
    await _require_installed_tenant(hub_id)

    client = HubSpotDataPullClient(hub_id)
    schemas = await client.discover_custom_object_schemas()
    await record_audit("debug_api_custom_object_schemas", hub_id=hub_id, detail={"schema_count": len(schemas)})
    return {"custom_object_schemas": schemas}


@router.get("/{hub_id}/custom-objects/{object_type_id}")
async def pull_custom_object_records(
    hub_id: str,
    object_type_id: str,
    properties: str | None = None,
    x_debug_api_key: str | None = Header(default=None),
) -> dict:
    """Pulls one custom object's records by its `objectTypeId` (from
    GET /{hub_id}/custom-objects above — there's no friendly-name lookup
    for a custom object the way there is for standard types). `properties`
    is an optional comma-separated list of exact property names, narrowing
    the response the same way it does for standard CRM object pulls."""
    _require_api_key(x_debug_api_key)
    await _require_installed_tenant(hub_id)

    requested_properties = _parse_properties_param(properties)

    client = HubSpotDataPullClient(hub_id)
    result = await client.pull_custom_object(object_type_id, properties=requested_properties)
    await record_audit(
        "debug_api_custom_object_pull",
        hub_id=hub_id,
        detail={"object_type_id": object_type_id, "properties": requested_properties},
    )
    return {"object_type_id": object_type_id, "records": result}


@router.get("/{hub_id}/campaigns")
async def pull_campaigns(hub_id: str, x_debug_api_key: str | None = Header(default=None)) -> dict:
    """Per-campaign attribution metrics for one real installed tenant —
    enumerates real campaigns first, then pulls each one's metrics.
    Empty on a portal without Marketing Hub Professional+ (CAMPAIGN is an
    optional OAuth scope for exactly this reason), not an error."""
    _require_api_key(x_debug_api_key)
    await _require_installed_tenant(hub_id)

    client = HubSpotDataPullClient(hub_id)
    result = await client.pull_campaign_data()
    await record_audit("debug_api_campaigns", hub_id=hub_id, detail={"campaign_count": len(result)})
    return {"campaigns": result}
