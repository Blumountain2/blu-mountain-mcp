"""Tests for main.py's own routes: the two discovery-metadata redirects that
compensate for URLs FastMCP can't construct correctly given the outer /mcp
mount (see design.md's decision log in the implement-hubspot-mcp-server
change for the full mechanism). Only main.py's own redirect logic is under
test here, not FastMCP's downstream behavior."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import main


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

    await main._run_audit_log_purge()

    purge_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_audit_log_purge_job_records_failure_instead_of_raising(monkeypatch):
    """A failed purge must be visible in the system's own audit log, not
    only in APScheduler's internal executor logger — otherwise a failure
    is invisible for up to a full 24-hour cycle."""
    monkeypatch.setattr(
        main, "purge_expired_audit_log", AsyncMock(side_effect=RuntimeError("db unavailable"))
    )
    audit_mock = AsyncMock()
    monkeypatch.setattr(main, "record_audit", audit_mock)

    await main._run_audit_log_purge()

    audit_mock.assert_awaited_once_with(
        "audit_log_purge_failed", detail={"error": "db unavailable"}
    )


@pytest.mark.asyncio
async def test_audit_log_purge_job_survives_outage_that_breaks_the_fallback_audit_too():
    """The realistic failure mode: the purge fails because Postgres itself is
    unreachable, so the fallback record_audit call — which hits the same
    pool — fails too. The job must not raise even then; this is exactly what
    a bare try/except around record_audit was added to guarantee."""
    with patch.object(
        main, "purge_expired_audit_log", AsyncMock(side_effect=RuntimeError("db unavailable"))
    ), patch.object(
        main, "record_audit", AsyncMock(side_effect=RuntimeError("db still unavailable"))
    ):
        await main._run_audit_log_purge()
