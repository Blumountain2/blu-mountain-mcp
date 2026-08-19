"""Task 2.11: unit tests for the refresh-buffer logic and cache TTL behavior."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from db import get_pool

from auth import (
    InMemoryAccessTokenCache,
    PostgresAccessTokenCache,
    TokenVault,
    derive_tenant_key,
    encrypt,
    mcp_vault,
    token_vault,
)


async def _seed_tenant(
    hub_id: str,
    access_token: str,
    refresh_token: str,
    expires_at: datetime,
    table: str = "tokens",
):
    pool = await get_pool()
    key = derive_tenant_key(hub_id)
    await pool.execute(
        "INSERT INTO tenants (hub_id) VALUES ($1) ON CONFLICT (hub_id) DO NOTHING", hub_id
    )
    await pool.execute(
        f"""
        INSERT INTO {table} (hub_id, encrypted_access_token, encrypted_refresh_token, expires_at)
        VALUES ($1, $2, $3, $4)
        """,
        hub_id,
        encrypt(access_token, key),
        encrypt(refresh_token, key),
        expires_at,
    )


@pytest.mark.asyncio
async def test_cache_set_get_round_trip():
    cache = InMemoryAccessTokenCache()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    await cache.set("hub_1", "access-token", expires_at)
    assert await cache.get("hub_1") == "access-token"


@pytest.mark.asyncio
async def test_cache_expired_entry_returns_none():
    cache = InMemoryAccessTokenCache()
    expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await cache.set("hub_1", "access-token", expires_at)
    assert await cache.get("hub_1") is None


@pytest.mark.asyncio
async def test_cache_invalidate_removes_entry():
    cache = InMemoryAccessTokenCache()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    await cache.set("hub_1", "access-token", expires_at)
    await cache.invalidate("hub_1")
    assert await cache.get("hub_1") is None


def test_token_vault_defaults_to_postgres_backed_cache():
    # The spec's required multi-instance baseline (Section 3.1) — not the
    # in-process fallback, which silently breaks cache consistency the
    # moment a second instance runs.
    assert isinstance(TokenVault()._cache, PostgresAccessTokenCache)


@pytest.mark.asyncio
async def test_postgres_cache_visible_to_a_fresh_instance_that_never_wrote_it():
    # The actual property this cache exists for: a *different* TokenVault/
    # cache instance (simulating a second mcp-gateway process) sees the
    # same cached value without ever having called get_access_token()
    # itself first — proving it's genuinely shared, not per-process state.
    await _seed_tenant(
        "hub_cross_instance", "cross-instance-access", "cross-instance-refresh",
        datetime.now(timezone.utc) + timedelta(hours=1),
    )
    fresh_cache = PostgresAccessTokenCache(table_name="tokens")
    assert await fresh_cache.get("hub_cross_instance") == "cross-instance-access"


@pytest.mark.asyncio
async def test_postgres_cache_returns_none_for_expired_row():
    await _seed_tenant(
        "hub_cache_expired", "stale-access", "stale-refresh",
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    cache = PostgresAccessTokenCache(table_name="tokens")
    assert await cache.get("hub_cache_expired") is None


@pytest.mark.asyncio
async def test_postgres_cache_returns_none_for_unknown_tenant():
    cache = PostgresAccessTokenCache(table_name="tokens")
    assert await cache.get("hub_never_seeded") is None


@pytest.mark.asyncio
async def test_postgres_cache_returns_none_within_refresh_buffer():
    # Regression case: a row inside the 5-minute refresh buffer (but not
    # yet hard-expired) must be treated as a cache miss, or a near-expiry
    # token would be served forever and proactive refresh would never run.
    await _seed_tenant(
        "hub_cache_near_expiry", "near-expiry-access", "near-expiry-refresh",
        datetime.now(timezone.utc) + timedelta(minutes=2),
    )
    cache = PostgresAccessTokenCache(table_name="tokens")
    assert await cache.get("hub_cache_near_expiry") is None


@pytest.mark.asyncio
async def test_get_access_token_does_not_refresh_when_far_from_expiry(monkeypatch):
    await _seed_tenant(
        "hub_far", "current-access", "current-refresh",
        datetime.now(timezone.utc) + timedelta(hours=1),
    )
    refresh_mock = AsyncMock()
    monkeypatch.setattr(token_vault, "refresh_token_pair", refresh_mock)

    vault = TokenVault()
    token = await vault.get_access_token("hub_far")

    assert token == "current-access"
    refresh_mock.assert_not_called()


@pytest.mark.asyncio
async def test_get_access_token_refreshes_within_buffer(monkeypatch):
    await _seed_tenant(
        "hub_near", "old-access", "old-refresh",
        datetime.now(timezone.utc) + timedelta(minutes=2),
    )
    new_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    refresh_mock = AsyncMock(return_value=("new-access", "new-refresh", new_expiry))
    monkeypatch.setattr(token_vault, "refresh_token_pair", refresh_mock)

    vault = TokenVault()
    token = await vault.get_access_token("hub_near")

    assert token == "new-access"
    refresh_mock.assert_called_once_with("old-refresh")

    pool = await get_pool()
    row = await pool.fetchrow("SELECT expires_at FROM tokens WHERE hub_id = $1", "hub_near")
    assert row["expires_at"] > datetime.now(timezone.utc) + timedelta(minutes=30)


@pytest.mark.asyncio
async def test_get_access_token_uses_cache_on_second_call(monkeypatch):
    await _seed_tenant(
        "hub_cached", "cached-access", "cached-refresh",
        datetime.now(timezone.utc) + timedelta(hours=1),
    )
    refresh_mock = AsyncMock()
    monkeypatch.setattr(token_vault, "refresh_token_pair", refresh_mock)

    vault = TokenVault()
    first = await vault.get_access_token("hub_cached")
    second = await vault.get_access_token("hub_cached")

    assert first == second == "cached-access"
    refresh_mock.assert_not_called()


@pytest.mark.asyncio
async def test_invalidate_removes_token_and_marks_uninstalled():
    await _seed_tenant(
        "hub_uninstall", "access", "refresh",
        datetime.now(timezone.utc) + timedelta(hours=1),
    )
    vault = TokenVault()
    await vault.invalidate("hub_uninstall")

    pool = await get_pool()
    token_row = await pool.fetchrow("SELECT * FROM tokens WHERE hub_id = $1", "hub_uninstall")
    tenant_row = await pool.fetchrow(
        "SELECT install_status FROM tenants WHERE hub_id = $1", "hub_uninstall"
    )
    assert token_row is None
    assert tenant_row["install_status"] == "uninstalled"


# mcp_vault: same TokenVault logic, parameterized against mcp_tokens with
# its own refresh_fn (mcp_auth.refresh_token_pair) and its own refresh/
# invalidate audit event names, and it must never mark a tenant uninstalled
# on invalidate (that's still owned exclusively by the Public App's vault).


@pytest.mark.asyncio
async def test_mcp_vault_reads_from_mcp_tokens_table():
    await _seed_tenant(
        "hub_mcp_far", "mcp-current-access", "mcp-current-refresh",
        datetime.now(timezone.utc) + timedelta(hours=1),
        table="mcp_tokens",
    )

    token = await mcp_vault.get_access_token("hub_mcp_far")

    assert token == "mcp-current-access"


@pytest.mark.asyncio
async def test_mcp_vault_refreshes_within_buffer_using_mcp_refresh_fn(monkeypatch):
    from auth import mcp_auth

    await _seed_tenant(
        "hub_mcp_near", "mcp-old-access", "mcp-old-refresh",
        datetime.now(timezone.utc) + timedelta(minutes=2),
        table="mcp_tokens",
    )
    new_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    refresh_mock = AsyncMock(return_value=("mcp-new-access", "mcp-new-refresh", new_expiry))
    monkeypatch.setattr(mcp_auth, "refresh_token_pair", refresh_mock)

    fresh_mcp_vault = token_vault._mcp_vault()
    token = await fresh_mcp_vault.get_access_token("hub_mcp_near")

    assert token == "mcp-new-access"
    refresh_mock.assert_called_once_with("mcp-old-refresh")

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT expires_at FROM mcp_tokens WHERE hub_id = $1", "hub_mcp_near"
    )
    assert row["expires_at"] > datetime.now(timezone.utc) + timedelta(minutes=30)


@pytest.mark.asyncio
async def test_mcp_vault_invalidate_does_not_mark_tenant_uninstalled():
    await _seed_tenant(
        "hub_mcp_uninstall", "mcp-access", "mcp-refresh",
        datetime.now(timezone.utc) + timedelta(hours=1),
        table="mcp_tokens",
    )
    await mcp_vault.invalidate("hub_mcp_uninstall")

    pool = await get_pool()
    token_row = await pool.fetchrow(
        "SELECT * FROM mcp_tokens WHERE hub_id = $1", "hub_mcp_uninstall"
    )
    tenant_row = await pool.fetchrow(
        "SELECT install_status FROM tenants WHERE hub_id = $1", "hub_mcp_uninstall"
    )
    assert token_row is None
    # Deliberately unaffected: mark_tenant_uninstalled_on_invalidate=False
    # for mcp_vault, since the Public App install/uninstall is the sole
    # owner of a tenant's overall install_status.
    assert tenant_row["install_status"] == "installed"
