"""Shared "next version" computation for this project's append-only
versioned tables (`analysis_content`, `vertical_agent_templates`,
`client_agent_instances`) — the same `SELECT COALESCE(MAX(version), 0)...
+ 1` sequence was duplicated identically across `store.py`,
`vertical_templates.py`, and `client_agent.py`'s own insert functions
before this was factored out. The INSERT itself stays in each module,
since the columns genuinely differ; only the version arithmetic is shared.
"""

import asyncpg


async def next_version(pool: asyncpg.Pool, table: str, where_sql: str, *params: object) -> int:
    """Returns one more than the current max `version` in `table` matching
    `where_sql` (a raw SQL WHERE clause using `$1`, `$2`, ... placeholders
    for `params`), or 1 if no matching row exists yet. `table`/`where_sql`
    are always caller-authored constants in this codebase, never derived
    from external input."""
    row = await pool.fetchrow(
        f"SELECT COALESCE(MAX(version), 0) AS max_version FROM {table} WHERE {where_sql}",
        *params,
    )
    return row["max_version"] + 1
