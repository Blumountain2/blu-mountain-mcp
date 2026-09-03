"""Persisted, staff-set tenant vertical (task 7.2,
openspec/changes/analysis-model-templates/tasks.md): the missing piece
`tenant-field-profiling`'s own spec already assumed was "knowable" — until
this, nothing in the built system ever stored it, `vertical` was only ever
a call-time parameter defaulting to None for every real tenant.

Never inferred automatically — a human decides which framework applies to
a client, matching this project's standing "human-review checkpoint"
posture (see frameworks/onboarding.py) rather than guessing from data.
"""

import structlog

from db import get_pool

from .ingest import FILE_MAP

logger = structlog.get_logger()

# Every real vertical name this project actually stores a framework for —
# derived from FILE_MAP rather than duplicated by hand, so a new vertical
# added there is automatically valid here too.
KNOWN_VERTICALS = frozenset(
    name for content_type, name in FILE_MAP.values() if content_type == "vertical_framework"
)


async def set_tenant_vertical(hub_id: str, vertical: str) -> None:
    """Sets hub_id's known vertical. Raises ValueError for a vertical this
    project has no stored framework for, rather than silently accepting a
    typo that would make every later framework lookup for this tenant
    return None."""
    if vertical not in KNOWN_VERTICALS:
        raise ValueError(f"Unknown vertical {vertical!r} (expected one of {sorted(KNOWN_VERTICALS)})")
    pool = await get_pool()
    result = await pool.execute(
        "UPDATE tenants SET vertical = $1, updated_at = now() WHERE hub_id = $2",
        vertical,
        hub_id,
    )
    if result.split()[-1] == "0":
        raise ValueError(f"Unknown tenant: {hub_id!r}")
    logger.info("frameworks.vertical.set", hub_id=hub_id, vertical=vertical)


async def get_tenant_vertical(hub_id: str) -> str | None:
    """Returns hub_id's known vertical, or None if not yet set — profiling
    and the pull agent both already handle an unknown vertical gracefully
    (specs/tenant-field-profiling/spec.md: "Profiling MAY still run,
    producing an unqualified result")."""
    pool = await get_pool()
    row = await pool.fetchrow("SELECT vertical FROM tenants WHERE hub_id = $1", hub_id)
    return row["vertical"] if row is not None else None


async def resolve_vertical_or_raise(
    hub_id: str,
    vertical: str | None,
    allow_unqualified: bool,
    purpose: str,
) -> str | None:
    """Shared by `onboarding.produce_onboarding_profile` and
    `client_agent.produce_client_agent_instance` — both need the identical
    "explicit argument, else the tenant's own stored vertical, else refuse"
    resolution, previously duplicated verbatim in each. Returns the
    resolved vertical (possibly None, only when `allow_unqualified=True`
    and nothing resolved). `purpose` is a short phrase describing what the
    vertical determines (e.g. "how this client's data is interpreted"),
    dropped into the refusal message so each caller's error still reads
    naturally."""
    if vertical is None:
        vertical = await get_tenant_vertical(hub_id)
    if vertical is None and not allow_unqualified:
        raise ValueError(
            f"Tenant {hub_id!r} has no vertical selected. A vertical determines {purpose} — "
            "set one first via frameworks.vertical.set_tenant_vertical(hub_id, vertical), or "
            "pass allow_unqualified=True to proceed without one."
        )
    return vertical
