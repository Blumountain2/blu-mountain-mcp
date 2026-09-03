"""Storage and retrieval for Blu Mountain's own-authored analysis content
(vertical frameworks, the operational skill, the runtime prompt) — see
openspec/changes/analysis-model-templates/. This module ingests and serves
that content; it never authors or rewrites it.

`analysis_content` is append-only by convention: `ingest()` always inserts a
new row, never updates one in place, so a tenant onboarding profile that
was produced against an earlier version can never have that version's
content silently change out from under it (analysis-template-schema's
versioning requirement).
"""

from dataclasses import dataclass

import structlog

from db import get_pool

from ._versioning import next_version

logger = structlog.get_logger()

# The skill and prompt types have exactly one real name each today, but
# nothing here assumes that stays true.
CONTENT_TYPE_FRAMEWORK = "vertical_framework"
CONTENT_TYPE_SKILL = "skill"
CONTENT_TYPE_PROMPT = "prompt"

# Added task 7.1 (openspec/changes/analysis-model-templates): the six
# per-vertical Challenge Library documents (one per CONTENT_TYPE_FRAMEWORK
# name, same naming convention), plus the two content-agnostic pieces —
# Blu_Operating_Principles and the 205-item Template Library, each with
# exactly one real name. Stored and served as reference content in their
# delivered form, never reformatted into operational-skill bodies (see
# specs/analysis-template-schema/spec.md and design.md's Open Questions —
# whether reformatting is ever warranted is still an open question for
# Blu Mountain, not something this project decides unilaterally).
CONTENT_TYPE_CHALLENGE_LIBRARY = "challenge_library"
CONTENT_TYPE_OPERATING_PRINCIPLES = "operating_principles"
CONTENT_TYPE_TEMPLATE_LIBRARY = "template_library"

_VALID_CONTENT_TYPES = {
    CONTENT_TYPE_FRAMEWORK,
    CONTENT_TYPE_SKILL,
    CONTENT_TYPE_PROMPT,
    CONTENT_TYPE_CHALLENGE_LIBRARY,
    CONTENT_TYPE_OPERATING_PRINCIPLES,
    CONTENT_TYPE_TEMPLATE_LIBRARY,
}


@dataclass(frozen=True)
class AnalysisContent:
    content_type: str
    name: str
    version: int
    content: str
    source_path: str | None


def _validate_content_type(content_type: str) -> None:
    if content_type not in _VALID_CONTENT_TYPES:
        raise ValueError(f"Unrecognized content_type: {content_type!r} (expected one of {_VALID_CONTENT_TYPES})")


async def ingest(content_type: str, name: str, content: str, source_path: str | None = None) -> int:
    """Inserts a new version of one named piece of content, never
    overwriting an earlier version. Returns the new version number
    (1 for a never-before-seen name, otherwise one more than the current
    latest). Concurrent ingests of the SAME (content_type, name) could
    race on the version number — not a concern for this content's real
    usage pattern (occasional, human-triggered re-ingestion of a small,
    fixed set of documents), so no additional locking is added here."""
    _validate_content_type(content_type)
    pool = await get_pool()
    new_version = await next_version(pool, "analysis_content", "content_type = $1 AND name = $2", content_type, name)
    await pool.execute(
        """
        INSERT INTO analysis_content (content_type, name, version, content, source_path)
        VALUES ($1, $2, $3, $4, $5)
        """,
        content_type,
        name,
        new_version,
        content,
        source_path,
    )
    logger.info("frameworks.ingested", content_type=content_type, name=name, version=new_version)
    return new_version


async def get_latest(content_type: str, name: str) -> AnalysisContent | None:
    """Returns the highest-versioned row for (content_type, name), or None
    if nothing has been ingested under that name yet."""
    _validate_content_type(content_type)
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT content_type, name, version, content, source_path FROM analysis_content "
        "WHERE content_type = $1 AND name = $2 ORDER BY version DESC LIMIT 1",
        content_type,
        name,
    )
    return AnalysisContent(**dict(row)) if row is not None else None


async def get_version(content_type: str, name: str, version: int) -> AnalysisContent | None:
    """Returns one specific version's row, so a caller holding an
    onboarding profile produced against an older version can always read
    exactly what that version said, even after a newer one is ingested."""
    _validate_content_type(content_type)
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT content_type, name, version, content, source_path FROM analysis_content "
        "WHERE content_type = $1 AND name = $2 AND version = $3",
        content_type,
        name,
        version,
    )
    return AnalysisContent(**dict(row)) if row is not None else None


async def list_latest(content_type: str | None = None) -> list[AnalysisContent]:
    """Lists the latest version of every distinct (content_type, name),
    optionally filtered to one content_type. Used for discovery — e.g.
    listing every vertical framework currently stored."""
    if content_type is not None:
        _validate_content_type(content_type)
    pool = await get_pool()
    query = """
        SELECT DISTINCT ON (content_type, name)
            content_type, name, version, content, source_path
        FROM analysis_content
        {where}
        ORDER BY content_type, name, version DESC
    """
    if content_type is not None:
        rows = await pool.fetch(query.format(where="WHERE content_type = $1"), content_type)
    else:
        rows = await pool.fetch(query.format(where=""))
    return [AnalysisContent(**dict(row)) for row in rows]
