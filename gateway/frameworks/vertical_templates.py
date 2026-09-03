"""Storage and retrieval for this project's own per-vertical agent
templates (openspec/changes/separate-vertical-client-agents) — this
project's own tool/model configuration layered around a vertical
framework's raw text, never a copy of that framework itself (the
framework stays shared, unmodified, and Blu-Mountain-authored in
`analysis_content`; see `store.py`).

`vertical_agent_templates` is append-only, mirroring `store.py`'s pattern
for `analysis_content` exactly: `ingest_template()` always inserts a new
version, never updates one in place, so a `client_agent_instances` row
built from an earlier version keeps reading that exact version's content
even after the vertical's template is updated.
"""

import json
from dataclasses import dataclass

import structlog

from db import get_pool

from ._versioning import next_version
from .vertical import KNOWN_VERTICALS

logger = structlog.get_logger()


@dataclass(frozen=True)
class VerticalAgentTemplate:
    id: int
    vertical: str
    version: int
    system_prompt_additions: str
    tool_config: dict


def _validate_vertical(vertical: str) -> None:
    if vertical not in KNOWN_VERTICALS:
        raise ValueError(f"Unknown vertical {vertical!r} (expected one of {sorted(KNOWN_VERTICALS)})")


async def ingest_template(vertical: str, system_prompt_additions: str, tool_config: dict | None = None) -> int:
    """Inserts a new version of one vertical's agent template, never
    overwriting an earlier version. Returns the new version number (1 for
    a never-before-seen vertical, otherwise one more than the current
    latest). Staff-editable directly — no separate review/ingestion
    pipeline, matching design.md's stated lean, since this is this
    project's own configuration rather than Blu Mountain's authored
    content."""
    _validate_vertical(vertical)
    pool = await get_pool()
    new_version = await next_version(pool, "vertical_agent_templates", "vertical = $1", vertical)
    await pool.execute(
        """
        INSERT INTO vertical_agent_templates (vertical, version, system_prompt_additions, tool_config)
        VALUES ($1, $2, $3, $4::jsonb)
        """,
        vertical,
        new_version,
        system_prompt_additions,
        _to_jsonb_text(tool_config),
    )
    logger.info("frameworks.vertical_templates.ingested", vertical=vertical, version=new_version)
    return new_version


def _to_jsonb_text(tool_config: dict | None) -> str:
    return json.dumps(tool_config or {})


def _row_to_template(row) -> VerticalAgentTemplate:
    tool_config = row["tool_config"]
    if isinstance(tool_config, str):
        tool_config = json.loads(tool_config)
    return VerticalAgentTemplate(
        id=row["id"],
        vertical=row["vertical"],
        version=row["version"],
        system_prompt_additions=row["system_prompt_additions"],
        tool_config=tool_config or {},
    )


async def get_latest_template(vertical: str) -> VerticalAgentTemplate | None:
    """Returns the highest-versioned template row for `vertical`, or None
    if nothing has been ingested for it yet."""
    _validate_vertical(vertical)
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, vertical, version, system_prompt_additions, tool_config "
        "FROM vertical_agent_templates WHERE vertical = $1 ORDER BY version DESC LIMIT 1",
        vertical,
    )
    return _row_to_template(row) if row is not None else None


async def get_template_version(vertical: str, version: int) -> VerticalAgentTemplate | None:
    """Returns one specific version's row, so a client agent instance
    built against an older version can always read exactly what that
    version said, even after a newer one is ingested."""
    _validate_vertical(vertical)
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, vertical, version, system_prompt_additions, tool_config "
        "FROM vertical_agent_templates WHERE vertical = $1 AND version = $2",
        vertical,
        version,
    )
    return _row_to_template(row) if row is not None else None


async def get_template_by_id(template_id: int) -> VerticalAgentTemplate | None:
    """Returns a template row by its surrogate id — used by
    `client_agent.py` to resolve the exact template a client instance
    references, without needing to know its vertical/version pair."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, vertical, version, system_prompt_additions, tool_config "
        "FROM vertical_agent_templates WHERE id = $1",
        template_id,
    )
    return _row_to_template(row) if row is not None else None


async def list_latest_templates() -> list[VerticalAgentTemplate]:
    """Lists the latest version of every vertical that has a template."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (vertical) id, vertical, version, system_prompt_additions, tool_config
        FROM vertical_agent_templates
        ORDER BY vertical, version DESC
        """
    )
    return [_row_to_template(row) for row in rows]
