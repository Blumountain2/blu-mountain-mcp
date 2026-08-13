"""Security hardening: per-tenant rate limiting and the shared audit log.

Credential hygiene (SC-2, SC-8) is enforced by convention across this
codebase, not by a runtime filter: no module logs a raw access token,
refresh token, or client secret. See the Security Controls checklist in
context/Hubspot for the SC-1 through SC-10 to test mapping.
"""

import json
from datetime import datetime, timedelta, timezone

import structlog

from config import settings
from db import get_pool

logger = structlog.get_logger()


async def record_audit(
    event_type: str, hub_id: str | None = None, staff_identity: str | None = None, detail: dict | None = None
) -> None:
    """Records one audit log entry (SC-6): every pull, credential access, and
    outcome, minimum 60-day retention, attributable to a tenant and, where
    applicable, a staff identity."""
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO audit_log (hub_id, staff_identity, event_type, detail) VALUES ($1, $2, $3, $4::jsonb)",
        hub_id,
        staff_identity,
        event_type,
        json.dumps(detail or {}, default=str),
    )


async def purge_expired_audit_log() -> int:
    """Deletes audit entries older than the configured retention window.
    Retention is a minimum, not a maximum, so this only prunes rows well past it."""
    pool = await get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.audit_retention_days)
    result = await pool.execute("DELETE FROM audit_log WHERE occurred_at < $1", cutoff)
    return int(result.split()[-1]) if result else 0


async def check_rate_limit(hub_id: str) -> bool:
    """Per-tenant Postgres token-bucket rate limit (SC-7). Returns True if the
    request is allowed, False if this tenant has exceeded its limit. One
    tenant's exhausted bucket never touches another tenant's row."""
    capacity = float(settings.rate_limit_per_minute)
    refill_per_second = capacity / 60.0

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT tokens, last_refill FROM rate_limit_buckets WHERE hub_id = $1 FOR UPDATE",
                hub_id,
            )
            now = datetime.now(timezone.utc)

            if row is None:
                tokens = capacity - 1
                await conn.execute(
                    "INSERT INTO rate_limit_buckets (hub_id, tokens, last_refill) VALUES ($1, $2, $3)",
                    hub_id,
                    tokens,
                    now,
                )
                return True

            elapsed = (now - row["last_refill"]).total_seconds()
            tokens = min(capacity, float(row["tokens"]) + elapsed * refill_per_second)

            if tokens < 1:
                await conn.execute(
                    "UPDATE rate_limit_buckets SET tokens = $2, last_refill = $3 WHERE hub_id = $1",
                    hub_id,
                    tokens,
                    now,
                )
                logger.warning("security.rate_limit_exceeded", hub_id=hub_id)
                return False

            await conn.execute(
                "UPDATE rate_limit_buckets SET tokens = $2, last_refill = $3 WHERE hub_id = $1",
                hub_id,
                tokens - 1,
                now,
            )
            return True
