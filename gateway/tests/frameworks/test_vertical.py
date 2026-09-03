"""Task 7.2 tests: a tenant's known vertical is staff-set and persisted,
never inferred, and validated against the verticals this project actually
has stored frameworks for."""

import pytest

from db import get_pool
from frameworks.vertical import KNOWN_VERTICALS, get_tenant_vertical, set_tenant_vertical


async def _seed_tenant(hub_id: str) -> None:
    pool = await get_pool()
    await pool.execute("INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'installed')", hub_id)


def test_known_verticals_matches_the_six_real_frameworks():
    assert KNOWN_VERTICALS == {
        "saas",
        "plg",
        "marketplace",
        "ecommerce",
        "services-project",
        "transactional",
    }


@pytest.mark.asyncio
async def test_get_tenant_vertical_is_none_until_set():
    await _seed_tenant("hub_a")
    assert await get_tenant_vertical("hub_a") is None


@pytest.mark.asyncio
async def test_set_then_get_round_trips():
    await _seed_tenant("hub_a")
    await set_tenant_vertical("hub_a", "saas")
    assert await get_tenant_vertical("hub_a") == "saas"


@pytest.mark.asyncio
async def test_set_rejects_an_unknown_vertical():
    await _seed_tenant("hub_a")
    with pytest.raises(ValueError):
        await set_tenant_vertical("hub_a", "advertising")


@pytest.mark.asyncio
async def test_set_rejects_an_unknown_tenant():
    with pytest.raises(ValueError):
        await set_tenant_vertical("no_such_hub", "saas")


@pytest.mark.asyncio
async def test_setting_one_tenants_vertical_never_affects_another():
    await _seed_tenant("hub_a")
    await _seed_tenant("hub_b")
    await set_tenant_vertical("hub_a", "saas")
    await set_tenant_vertical("hub_b", "ecommerce")

    assert await get_tenant_vertical("hub_a") == "saas"
    assert await get_tenant_vertical("hub_b") == "ecommerce"
