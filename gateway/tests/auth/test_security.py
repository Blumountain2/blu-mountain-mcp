"""Per-tenant Postgres token-bucket rate limiting (SC-7), and audit log
retention (SC-6)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from config import settings
from db import get_pool

from auth import check_rate_limit, purge_expired_audit_log, record_audit, record_audit_best_effort
from auth import security


@pytest.mark.asyncio
async def test_rate_limit_allows_up_to_capacity(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 3)

    results = [await check_rate_limit("hub_capacity") for _ in range(3)]
    assert all(results)


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_capacity_exhausted(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)

    assert await check_rate_limit("hub_exhaust") is True
    assert await check_rate_limit("hub_exhaust") is True
    assert await check_rate_limit("hub_exhaust") is False


@pytest.mark.asyncio
async def test_rate_limit_isolated_per_tenant(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1)

    assert await check_rate_limit("hub_a") is True
    assert await check_rate_limit("hub_a") is False
    # Tenant B's bucket is untouched by tenant A's exhaustion.
    assert await check_rate_limit("hub_b") is True


@pytest.mark.asyncio
async def test_record_audit_creates_entry_with_expected_fields():
    await record_audit("test_event", hub_id="hub_a", staff_identity="staff@blumountain.me", detail={"k": "v"})

    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM audit_log WHERE event_type = 'test_event'")
    assert row["hub_id"] == "hub_a"
    assert row["staff_identity"] == "staff@blumountain.me"


@pytest.mark.asyncio
async def test_purge_expired_audit_log_only_removes_entries_past_retention(monkeypatch):
    monkeypatch.setattr(settings, "audit_retention_days", 60)

    pool = await get_pool()
    old_time = datetime.now(timezone.utc) - timedelta(days=90)
    recent_time = datetime.now(timezone.utc) - timedelta(days=1)

    await pool.execute(
        "INSERT INTO audit_log (occurred_at, event_type, detail) VALUES ($1, 'old_event', '{}'::jsonb)",
        old_time,
    )
    await pool.execute(
        "INSERT INTO audit_log (occurred_at, event_type, detail) VALUES ($1, 'recent_event', '{}'::jsonb)",
        recent_time,
    )

    await purge_expired_audit_log()

    remaining = await pool.fetch("SELECT event_type FROM audit_log")
    remaining_types = {row["event_type"] for row in remaining}
    assert "old_event" not in remaining_types
    assert "recent_event" in remaining_types


@pytest.mark.asyncio
async def test_record_audit_best_effort_writes_a_real_entry():
    await record_audit_best_effort("test_best_effort_event", hub_id="hub_a", detail={"k": "v"})

    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM audit_log WHERE event_type = 'test_best_effort_event'")
    assert row is not None
    assert row["hub_id"] == "hub_a"


@pytest.mark.asyncio
async def test_record_audit_best_effort_swallows_a_failure_in_the_audit_write_itself(monkeypatch):
    """The realistic scenario this helper exists for: whatever the caller
    was already handling failed, and the audit write itself then also
    fails (most plausibly the same underlying outage) — this must not
    raise, or the caller's own error handling would be aborted by a
    second, unrelated exception."""
    monkeypatch.setattr(security, "record_audit", AsyncMock(side_effect=RuntimeError("db unavailable")))

    await record_audit_best_effort("test_event", hub_id="hub_a", detail={})  # must not raise
