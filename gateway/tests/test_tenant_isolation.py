"""Tasks 8.1-8.4: cross-tenant isolation under concurrent load, across the
token vault and the live session's tenant-selection enforcement."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from db import get_pool

from auth import TokenVault, derive_tenant_key, encrypt, token_vault
from session.live_session import (
    TenantNotPermitted,
    TenantSelectionRequired,
    _resolve_selected_tenant,
    select_tenant_internal,
)


async def _seed_tenant(hub_id: str, expires_at: datetime):
    pool = await get_pool()
    key = derive_tenant_key(hub_id)
    await pool.execute("INSERT INTO tenants (hub_id) VALUES ($1)", hub_id)
    await pool.execute(
        """
        INSERT INTO tokens (hub_id, encrypted_access_token, encrypted_refresh_token, expires_at)
        VALUES ($1, $2, $3, $4)
        """,
        hub_id,
        encrypt(f"access-{hub_id}", key),
        encrypt(f"refresh-{hub_id}", key),
        expires_at,
    )


async def _seed_mcp_tenant(hub_id: str, expires_at: datetime):
    pool = await get_pool()
    key = derive_tenant_key(hub_id)
    await pool.execute(
        "INSERT INTO tenants (hub_id) VALUES ($1) ON CONFLICT (hub_id) DO NOTHING", hub_id
    )
    await pool.execute(
        """
        INSERT INTO mcp_tokens (hub_id, encrypted_access_token, encrypted_refresh_token, expires_at)
        VALUES ($1, $2, $3, $4)
        """,
        hub_id,
        encrypt(f"mcp-access-{hub_id}", key),
        encrypt(f"mcp-refresh-{hub_id}", key),
        expires_at,
    )


async def _restrict(staff: str, hub_id: str):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO staff_tenant_restrictions (staff_identity, hub_id) VALUES ($1, $2)",
        staff,
        hub_id,
    )


@pytest.mark.asyncio
async def test_concurrent_refresh_same_tenant_refreshes_once(monkeypatch):
    await _seed_tenant("hub_concurrent", datetime.now(timezone.utc) + timedelta(minutes=1))

    new_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    refresh_mock = AsyncMock(return_value=("new-access", "new-refresh", new_expiry))
    monkeypatch.setattr(token_vault, "refresh_token_pair", refresh_mock)

    vault_a = TokenVault()
    vault_b = TokenVault()
    results = await asyncio.gather(
        vault_a.get_access_token("hub_concurrent"),
        vault_b.get_access_token("hub_concurrent"),
    )

    assert all(r == "new-access" for r in results)
    # The advisory lock serializes both calls on this tenant; only one
    # actually hits the (near-expiry) refresh path.
    assert refresh_mock.call_count == 1


@pytest.mark.asyncio
async def test_concurrent_refresh_different_tenants_isolated(monkeypatch):
    await _seed_tenant("hub_x", datetime.now(timezone.utc) + timedelta(minutes=1))
    await _seed_tenant("hub_y", datetime.now(timezone.utc) + timedelta(minutes=1))

    new_expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    async def fake_refresh(refresh_token: str):
        return (f"new-{refresh_token}", f"newer-{refresh_token}", new_expiry)

    monkeypatch.setattr(token_vault, "refresh_token_pair", fake_refresh)

    vault = TokenVault()
    token_x, token_y = await asyncio.gather(
        vault.get_access_token("hub_x"),
        vault.get_access_token("hub_y"),
    )

    assert token_x == "new-refresh-hub_x"
    assert token_y == "new-refresh-hub_y"
    assert token_x != token_y


@pytest.mark.asyncio
async def test_concurrent_refresh_same_tenant_via_mcp_vault_refreshes_once(monkeypatch):
    """mcp_vault (the MCP Auth App's credential) must get the exact same
    per-tenant serialization guarantee as the Public App's default vault —
    this is the multi-tenant isolation proof for the second vaulted
    credential, not just the first."""
    from auth import mcp_auth

    await _seed_mcp_tenant("hub_mcp_concurrent", datetime.now(timezone.utc) + timedelta(minutes=1))

    new_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    refresh_mock = AsyncMock(return_value=("mcp-new-access", "mcp-new-refresh", new_expiry))
    monkeypatch.setattr(mcp_auth, "refresh_token_pair", refresh_mock)

    vault_a = token_vault._mcp_vault()
    vault_b = token_vault._mcp_vault()
    results = await asyncio.gather(
        vault_a.get_access_token("hub_mcp_concurrent"),
        vault_b.get_access_token("hub_mcp_concurrent"),
    )

    assert all(r == "mcp-new-access" for r in results)
    assert refresh_mock.call_count == 1


@pytest.mark.asyncio
async def test_concurrent_refresh_different_tenants_via_mcp_vault_isolated(monkeypatch):
    from auth import mcp_auth

    await _seed_mcp_tenant("hub_mcp_x", datetime.now(timezone.utc) + timedelta(minutes=1))
    await _seed_mcp_tenant("hub_mcp_y", datetime.now(timezone.utc) + timedelta(minutes=1))

    new_expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    async def fake_refresh(refresh_token: str):
        return (f"new-{refresh_token}", f"newer-{refresh_token}", new_expiry)

    monkeypatch.setattr(mcp_auth, "refresh_token_pair", fake_refresh)

    vault = token_vault._mcp_vault()
    token_x, token_y = await asyncio.gather(
        vault.get_access_token("hub_mcp_x"),
        vault.get_access_token("hub_mcp_y"),
    )

    assert token_x == "new-mcp-refresh-hub_mcp_x"
    assert token_y == "new-mcp-refresh-hub_mcp_y"
    assert token_x != token_y


@pytest.mark.asyncio
async def test_vault_and_mcp_vault_refresh_same_tenant_dont_block_each_other(monkeypatch):
    """The two vaults are independent tables with no data dependency for
    the same tenant — the advisory lock must be scoped per table, not just
    per hub_id, or a Public App refresh and an MCP Auth App refresh for
    the SAME tenant would serialize against each other for no reason. This
    is a real deadlock risk if that scoping regresses: the mcp refresh
    below only completes by releasing the event the (otherwise-independent)
    public refresh is waiting on — if the two locks wrongly conflicted,
    the mcp refresh could never even start until the public one finishes,
    and the public one would then wait forever. asyncio.wait_for turns
    that hang into a clean test failure instead of blocking the suite."""
    from auth import mcp_auth

    hub_id = "hub_both_vaults"
    await _seed_tenant(hub_id, datetime.now(timezone.utc) + timedelta(minutes=1))
    await _seed_mcp_tenant(hub_id, datetime.now(timezone.utc) + timedelta(minutes=1))

    new_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    release_public_refresh = asyncio.Event()

    async def slow_public_refresh(refresh_token):
        await release_public_refresh.wait()
        return ("public-access", "public-refresh", new_expiry)

    async def fast_mcp_refresh(refresh_token):
        release_public_refresh.set()
        return ("mcp-access", "mcp-refresh", new_expiry)

    monkeypatch.setattr(token_vault, "refresh_token_pair", slow_public_refresh)
    monkeypatch.setattr(mcp_auth, "refresh_token_pair", fast_mcp_refresh)

    public_token, mcp_token = await asyncio.wait_for(
        asyncio.gather(
            TokenVault().get_access_token(hub_id),
            token_vault._mcp_vault().get_access_token(hub_id),
        ),
        timeout=5,
    )

    assert public_token == "public-access"
    assert mcp_token == "mcp-access"


@pytest.mark.asyncio
async def test_live_session_default_open_access_with_no_restrictions():
    """A staff member with zero rows in staff_tenant_restrictions still gets
    access to an installed tenant automatically — access requires no grant,
    only the absence of an explicit restriction."""
    await _seed_tenant("hub_default", datetime.now(timezone.utc) + timedelta(hours=1))

    selected = await _resolve_selected_tenant("brand_new_staff@blumountain.me", "session-new")
    assert selected == "hub_default"


@pytest.mark.asyncio
async def test_live_session_uninstalled_tenant_not_in_default_access():
    await _seed_tenant("hub_active", datetime.now(timezone.utc) + timedelta(hours=1))
    await _seed_tenant("hub_uninstalled", datetime.now(timezone.utc) + timedelta(hours=1))
    pool = await get_pool()
    await pool.execute(
        "UPDATE tenants SET install_status = 'uninstalled' WHERE hub_id = $1",
        "hub_uninstalled",
    )

    selected = await _resolve_selected_tenant("staff@blumountain.me", "session-uninstall")
    assert selected == "hub_active"


@pytest.mark.asyncio
async def test_live_session_restricted_tenant_rejected():
    await _seed_tenant("hub_allowed", datetime.now(timezone.utc) + timedelta(hours=1))
    await _seed_tenant("hub_restricted", datetime.now(timezone.utc) + timedelta(hours=1))
    await _restrict("staff@blumountain.me", "hub_restricted")

    with pytest.raises(TenantNotPermitted):
        await select_tenant_internal("staff@blumountain.me", "session-1", "hub_restricted")

    # Default-open: the same staff member still has access to the tenant
    # they were never explicitly restricted from.
    await select_tenant_internal("staff@blumountain.me", "session-1", "hub_allowed")


@pytest.mark.asyncio
async def test_live_session_restriction_matches_regardless_of_hand_typed_casing():
    """A restriction row hand-typed with different casing than the staff
    member's actual (lowercased) email must still apply — this is the exact
    fail-open scenario the LOWER() comparison in _permitted_tenants exists
    to close, not just the token-side .lower() alone."""
    await _seed_tenant("hub_sensitive", datetime.now(timezone.utc) + timedelta(hours=1))
    await _restrict("Person@BluMountain.me", "hub_sensitive")

    with pytest.raises(TenantNotPermitted):
        await select_tenant_internal("person@blumountain.me", "session-case", "hub_sensitive")


@pytest.mark.asyncio
async def test_live_session_never_installed_tenant_rejected():
    """A hub_id that was never seeded into tenants at all — not restricted,
    not uninstalled, simply never existed — must never be selectable."""
    await _seed_tenant("hub_real", datetime.now(timezone.utc) + timedelta(hours=1))

    with pytest.raises(TenantNotPermitted):
        await select_tenant_internal("staff@blumountain.me", "session-fake", "hub_never_existed")


@pytest.mark.asyncio
async def test_live_session_restriction_added_mid_session_takes_effect_immediately():
    """A restriction added after a tenant was already selected must reject
    the very next query for that session, not be masked by the cached
    selection in live_session_selection."""
    await _seed_tenant("hub_selected", datetime.now(timezone.utc) + timedelta(hours=1))
    await _seed_tenant("hub_other", datetime.now(timezone.utc) + timedelta(hours=1))

    await select_tenant_internal("staff@blumountain.me", "session-mid", "hub_selected")
    assert await _resolve_selected_tenant("staff@blumountain.me", "session-mid") == "hub_selected"

    # Restricted after the fact, while another tenant remains permitted, so
    # the staff member isn't left with zero permitted tenants either.
    await _restrict("staff@blumountain.me", "hub_selected")

    with pytest.raises(TenantNotPermitted):
        await _resolve_selected_tenant("staff@blumountain.me", "session-mid")


@pytest.mark.asyncio
async def test_live_session_multi_tenant_requires_explicit_selection():
    await _seed_tenant("hub_1", datetime.now(timezone.utc) + timedelta(hours=1))
    await _seed_tenant("hub_2", datetime.now(timezone.utc) + timedelta(hours=1))

    with pytest.raises(TenantSelectionRequired):
        await _resolve_selected_tenant("staff@blumountain.me", "session-2")


@pytest.mark.asyncio
async def test_live_session_single_tenant_auto_selected():
    await _seed_tenant("hub_only", datetime.now(timezone.utc) + timedelta(hours=1))

    selected = await _resolve_selected_tenant("staff@blumountain.me", "session-3")
    assert selected == "hub_only"


@pytest.mark.asyncio
async def test_live_session_two_staff_sessions_do_not_leak_selection():
    await _seed_tenant("hub_a", datetime.now(timezone.utc) + timedelta(hours=1))
    await _seed_tenant("hub_b", datetime.now(timezone.utc) + timedelta(hours=1))
    await _seed_tenant("hub_c", datetime.now(timezone.utc) + timedelta(hours=1))
    # staff_b is restricted from everything but hub_c, so their session
    # auto-selects it; staff_a explicitly picks among all three instead.
    await _restrict("staff_b@blumountain.me", "hub_a")
    await _restrict("staff_b@blumountain.me", "hub_b")

    await select_tenant_internal("staff_a@blumountain.me", "session-a", "hub_a")

    # staff_b's session was never given a selection; resolving it must never
    # see, or be satisfied by, staff_a's selection.
    selected_b = await _resolve_selected_tenant("staff_b@blumountain.me", "session-b")
    assert selected_b == "hub_c"


@pytest.mark.asyncio
async def test_live_session_default_open_selection_never_leaks_another_tenants_data():
    """The actual new risk default-open introduces: with multiple installed
    tenants and zero restrictions (the common case for any unrestricted
    staff member), selecting and resolving one tenant must never return
    another tenant's hub_id, and the vaulted token reachable through that
    resolution must belong to the selected tenant alone."""
    await _seed_tenant("hub_leak_a", datetime.now(timezone.utc) + timedelta(hours=1))
    await _seed_tenant("hub_leak_b", datetime.now(timezone.utc) + timedelta(hours=1))

    await select_tenant_internal("staff@blumountain.me", "session-leak", "hub_leak_a")
    resolved = await _resolve_selected_tenant("staff@blumountain.me", "session-leak")

    assert resolved == "hub_leak_a"
    assert resolved != "hub_leak_b"

    vault = TokenVault()
    access_token = await vault.get_access_token(resolved)
    assert access_token == "access-hub_leak_a"
