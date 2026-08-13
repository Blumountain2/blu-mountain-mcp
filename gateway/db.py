"""Postgres connection pool and schema bootstrap."""

from pathlib import Path

import asyncpg

from config import settings

_pool: asyncpg.Pool | None = None

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_schema() -> None:
    """Applies schema.sql on every startup. Each statement individually is
    safe to re-run (CREATE ... IF NOT EXISTS, or an explicit DROP TABLE IF
    EXISTS for a table a migration superseded) — but that's a property each
    new statement must maintain deliberately, not something guaranteed by
    this function itself. Check that before adding anything destructive."""
    pool = await get_pool()
    ddl = _SCHEMA_PATH.read_text()
    async with pool.acquire() as conn:
        await conn.execute(ddl)
