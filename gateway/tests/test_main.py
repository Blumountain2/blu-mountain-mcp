"""Tests for main.py's own routes: the two discovery-metadata redirects that
compensate for URLs FastMCP can't construct correctly given the outer /mcp
mount (see design.md's decision log in the implement-hubspot-mcp-server
change for the full mechanism). Only main.py's own redirect logic is under
test here, not FastMCP's downstream behavior."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import main
from auth import security


@pytest.mark.asyncio
async def test_protected_resource_metadata_redirects_to_working_path():
    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.get(f"/.well-known/oauth-protected-resource/{main._MCP_MOUNT_SUFFIX}")

    assert response.status_code == 307
    assert response.headers["location"] == (
        f"{main._MCP_MOUNT_PATH}/.well-known/oauth-protected-resource/{main._MCP_MOUNT_SUFFIX}/"
    )


@pytest.mark.asyncio
async def test_protected_resource_metadata_redirect_trailing_slash_variant():
    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.get(f"/.well-known/oauth-protected-resource/{main._MCP_MOUNT_SUFFIX}/")

    assert response.status_code == 307
    assert response.headers["location"] == (
        f"{main._MCP_MOUNT_PATH}/.well-known/oauth-protected-resource/{main._MCP_MOUNT_SUFFIX}/"
    )


@pytest.mark.asyncio
async def test_authorization_server_metadata_redirects_to_working_path():
    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.get(f"/.well-known/oauth-authorization-server/{main._MCP_MOUNT_SUFFIX}")

    assert response.status_code == 307
    assert response.headers["location"] == (
        f"{main._MCP_MOUNT_PATH}/.well-known/oauth-authorization-server"
    )


@pytest.mark.asyncio
async def test_audit_log_purge_job_deletes_and_logs(monkeypatch):
    purge_mock = AsyncMock(return_value=7)
    monkeypatch.setattr(main, "purge_expired_audit_log", purge_mock)
    recorded_calls: list = []
    monkeypatch.setattr(main, "logger", SimpleNamespace(info=lambda *a, **kw: recorded_calls.append((a, kw))))

    await main._run_audit_log_purge()

    purge_mock.assert_awaited_once()
    # Checks the real logged value, not just that *some* log call
    # happened — this is what actually proves "deletes_and_logs," not
    # just "deletes."
    assert recorded_calls == [(("audit_log_purge.completed",), {"rows_deleted": 7})]


@pytest.mark.asyncio
async def test_audit_log_purge_job_records_failure_instead_of_raising(monkeypatch):
    """A failed purge must be visible in the system's own audit log, not
    only in APScheduler's internal executor logger — otherwise a failure
    is invisible for up to a full 24-hour cycle."""
    monkeypatch.setattr(
        main, "purge_expired_audit_log", AsyncMock(side_effect=RuntimeError("db unavailable"))
    )
    # main.py now delegates the "record this failure, best-effort" step to
    # the shared auth.record_audit_best_effort helper (see auth/security.py)
    # rather than calling record_audit directly — patch that call boundary.
    best_effort_mock = AsyncMock()
    monkeypatch.setattr(main, "record_audit_best_effort", best_effort_mock)

    await main._run_audit_log_purge()

    best_effort_mock.assert_awaited_once_with(
        "audit_log_purge_failed", detail={"error": "db unavailable"}
    )


@pytest.mark.asyncio
async def test_audit_log_purge_job_survives_outage_that_breaks_the_fallback_audit_too():
    """The realistic failure mode: the purge fails because Postgres itself is
    unreachable, so the fallback record_audit call — which hits the same
    pool — fails too. The job must not raise even then; this is exactly what
    auth.record_audit_best_effort's own try/except is shared to guarantee."""
    with patch.object(
        main, "purge_expired_audit_log", AsyncMock(side_effect=RuntimeError("db unavailable"))
    ), patch.object(
        security, "record_audit", AsyncMock(side_effect=RuntimeError("db still unavailable"))
    ):
        await main._run_audit_log_purge()


@pytest.mark.asyncio
async def test_scheduled_job_error_listener_records_audit_for_any_job():
    """The global safety net: any scheduled job's exception, from any
    origin, gets recorded here — not just the ones each job's own code
    happens to catch itself. Exercises the listener the same way
    APScheduler itself would invoke it: synchronously, with a
    JobExecutionEvent-shaped object."""
    record_audit_mock = AsyncMock()
    with patch.object(main, "record_audit_best_effort", record_audit_mock):
        fake_event = SimpleNamespace(job_id="some_future_job", exception=RuntimeError("boom"))
        main._on_scheduled_job_error(fake_event)

        # _on_scheduled_job_error schedules record_audit_best_effort via
        # asyncio.create_task rather than awaiting it directly, since
        # APScheduler invokes listeners synchronously even under
        # AsyncIOScheduler — give the loop one turn so that task actually
        # runs before asserting on it.
        await asyncio.sleep(0)

    record_audit_mock.assert_awaited_once()
    args, kwargs = record_audit_mock.call_args
    assert args[0] == "scheduled_job_failed"
    assert kwargs["detail"]["job_id"] == "some_future_job"
    assert "boom" in kwargs["detail"]["error"]


@pytest.mark.asyncio
async def test_scheduled_job_error_listener_retains_its_task_until_done():
    """asyncio only holds a weak reference to a task with no other
    referent — an unreferenced task can be garbage-collected mid-execution,
    silently dropping the audit write this listener exists to guarantee.
    _pending_job_error_audits must hold a strong reference for the task's
    lifetime and release it once done, not leak forever."""
    with patch.object(main, "record_audit_best_effort", AsyncMock()):
        fake_event = SimpleNamespace(job_id="another_job", exception=RuntimeError("boom"))
        assert len(main._pending_job_error_audits) == 0

        main._on_scheduled_job_error(fake_event)
        assert len(main._pending_job_error_audits) == 1

        # One sleep(0) lets the task itself run to completion; its
        # add_done_callback (which discards it from the set) is scheduled
        # via call_soon at that point and only fires on a subsequent loop
        # iteration, hence the second sleep(0).
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(main._pending_job_error_audits) == 0
