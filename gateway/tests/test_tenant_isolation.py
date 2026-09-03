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
