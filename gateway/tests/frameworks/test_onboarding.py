"""Task 3 tests (specs/tenant-template-instantiation/spec.md): an
onboarding profile is produced from exactly one tenant's field profile,
named after that tenant, auto-confirms only fields the tenant's known
framework already has explicit guidance for, requires human review for
everything else, and is structurally usable only for the tenant it was
produced for."""

import pytest

from db import get_pool
from frameworks import onboarding
from frameworks.onboarding import (
    STATUS_CONFIRMED_IRRELEVANT,
    STATUS_CONFIRMED_RELEVANT,
    STATUS_NEEDS_REVIEW,
    get_profile_for_tenant,
    produce_onboarding_profile,
    review_field,
)
from frameworks.profiling import FieldProfile
from frameworks.vertical import set_tenant_vertical


async def _seed_tenant(hub_id: str, portal_name: str | None = None, hub_domain: str | None = None) -> None:
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id, portal_name, hub_domain, install_status) "
        "VALUES ($1, $2, $3, 'installed')",
        hub_id,
        portal_name,
        hub_domain,
    )


def _fake_profiled(monkeypatch, result: dict):
    async def fake_profile_tenant_fields(hub_id, object_types, vertical=None):
        return result

    monkeypatch.setattr(onboarding, "profile_tenant_fields", fake_profile_tenant_fields)


# --- naming (task 3.2) ---


@pytest.mark.asyncio
async def test_profile_is_named_after_portal_name_when_present(monkeypatch):
    await _seed_tenant("hub_a", portal_name="Acme Inc", hub_domain="acme.com")
    _fake_profiled(monkeypatch, {})

    profile_id = await produce_onboarding_profile("hub_a", object_types=["COMPANY"], allow_unqualified=True)
    profile = await get_profile_for_tenant("hub_a", profile_id)

    assert profile.name == "Acme Inc"


@pytest.mark.asyncio
async def test_profile_name_falls_back_to_hub_domain_then_hub_id(monkeypatch):
    await _seed_tenant("hub_b", hub_domain="beta.example.com")
    _fake_profiled(monkeypatch, {})
    profile_id = await produce_onboarding_profile("hub_b", object_types=["COMPANY"], allow_unqualified=True)
    assert (await get_profile_for_tenant("hub_b", profile_id)).name == "beta.example.com"

    await _seed_tenant("hub_c")
    profile_id = await produce_onboarding_profile("hub_c", object_types=["COMPANY"], allow_unqualified=True)
    assert (await get_profile_for_tenant("hub_c", profile_id)).name == "hub_c"


# --- field status logic ---


@pytest.mark.asyncio
async def test_populated_field_with_framework_guidance_is_auto_confirmed(monkeypatch):
    await _seed_tenant("hub_a")
    _fake_profiled(
        monkeypatch,
        {"COMPANY": [FieldProfile("hs_object_source", True, 1, 1, "trust_by_default")]},
    )

    profile_id = await produce_onboarding_profile("hub_a", object_types=["COMPANY"], vertical="saas")
    profile = await get_profile_for_tenant("hub_a", profile_id)

    assert len(profile.fields) == 1
    assert profile.fields[0].status == STATUS_CONFIRMED_RELEVANT
    assert profile.fields[0].framework_guidance == "trust_by_default"


@pytest.mark.asyncio
async def test_populated_field_without_framework_guidance_needs_review(monkeypatch):
    await _seed_tenant("hub_a")
    _fake_profiled(
        monkeypatch,
        {"COMPANY": [FieldProfile("some_custom_field", True, 1, 1, None)]},
    )

    profile_id = await produce_onboarding_profile("hub_a", object_types=["COMPANY"], allow_unqualified=True)
    profile = await get_profile_for_tenant("hub_a", profile_id)

    assert profile.fields[0].status == STATUS_NEEDS_REVIEW
    assert profile.is_final is False


@pytest.mark.asyncio
async def test_unpopulated_field_is_excluded_from_the_profile(monkeypatch):
    await _seed_tenant("hub_a")
    _fake_profiled(
        monkeypatch,
        {"COMPANY": [FieldProfile("stale_field", False, 0, 3, None)]},
    )

    profile_id = await produce_onboarding_profile("hub_a", object_types=["COMPANY"], allow_unqualified=True)
    profile = await get_profile_for_tenant("hub_a", profile_id)

    assert profile.fields == []
    assert profile.is_final is True  # nothing to review


@pytest.mark.asyncio
async def test_profile_with_no_needs_review_fields_is_final(monkeypatch):
    await _seed_tenant("hub_a")
    _fake_profiled(
        monkeypatch,
        {"COMPANY": [FieldProfile("hs_object_source", True, 1, 1, "trust_by_default")]},
    )

    profile_id = await produce_onboarding_profile("hub_a", object_types=["COMPANY"], allow_unqualified=True)
    profile = await get_profile_for_tenant("hub_a", profile_id)

    assert profile.is_final is True


# --- human review checkpoint (task 3.3) ---


@pytest.mark.asyncio
async def test_review_field_moves_a_pending_field_to_confirmed_relevant(monkeypatch):
    await _seed_tenant("hub_a")
    _fake_profiled(monkeypatch, {"COMPANY": [FieldProfile("some_field", True, 1, 1, None)]})
    profile_id = await produce_onboarding_profile("hub_a", object_types=["COMPANY"], allow_unqualified=True)
    assert (await get_profile_for_tenant("hub_a", profile_id)).is_final is False

    updated = await review_field("hub_a", profile_id, "COMPANY", "some_field", True, "reviewer@blumountain.me")

    assert updated is True
    profile = await get_profile_for_tenant("hub_a", profile_id)
    assert profile.fields[0].status == STATUS_CONFIRMED_RELEVANT
    assert profile.is_final is True


@pytest.mark.asyncio
async def test_review_field_can_reject_a_field_as_irrelevant(monkeypatch):
    await _seed_tenant("hub_a")
    _fake_profiled(monkeypatch, {"COMPANY": [FieldProfile("some_field", True, 1, 1, None)]})
    profile_id = await produce_onboarding_profile("hub_a", object_types=["COMPANY"], allow_unqualified=True)

    await review_field("hub_a", profile_id, "COMPANY", "some_field", False, "reviewer@blumountain.me")

    profile = await get_profile_for_tenant("hub_a", profile_id)
    assert profile.fields[0].status == STATUS_CONFIRMED_IRRELEVANT
    assert profile.is_final is True


# --- isolation (task 3.4) ---


@pytest.mark.asyncio
async def test_get_profile_for_tenant_returns_none_for_the_wrong_tenant(monkeypatch):
    await _seed_tenant("hub_a")
    await _seed_tenant("hub_b")
    _fake_profiled(monkeypatch, {})
    profile_id = await produce_onboarding_profile("hub_a", object_types=["COMPANY"], allow_unqualified=True)

    assert await get_profile_for_tenant("hub_b", profile_id) is None
    assert await get_profile_for_tenant("hub_a", profile_id) is not None


@pytest.mark.asyncio
async def test_review_field_cannot_target_another_tenants_profile(monkeypatch):
    await _seed_tenant("hub_a")
    await _seed_tenant("hub_b")
    _fake_profiled(monkeypatch, {"COMPANY": [FieldProfile("some_field", True, 1, 1, None)]})
    profile_id = await produce_onboarding_profile("hub_a", object_types=["COMPANY"], allow_unqualified=True)

    updated = await review_field("hub_b", profile_id, "COMPANY", "some_field", True, "attacker@example.com")

    assert updated is False
    profile = await get_profile_for_tenant("hub_a", profile_id)
    assert profile.fields[0].status == STATUS_NEEDS_REVIEW  # unchanged


@pytest.mark.asyncio
async def test_produce_onboarding_profile_only_ever_constructs_client_for_the_requested_tenant(monkeypatch):
    """Isolation at the HubSpot-pull layer, not just the storage layer:
    producing tenant A's profile never opens tenant B's connection.

    Spies on profiling.profile_tenant_fields's own hub_id argument rather
    than reimplementing profile_tenant_fields's already-covered fake MCP
    transport (that whole stack is exercised and asserted independently
    in test_profiling.py) — the only new fact this test needs to prove is
    that produce_onboarding_profile passes hub_id through unchanged."""
    await _seed_tenant("hub_only_this_one")

    seen_hub_ids = []

    async def _recording_profile_fields(hub_id, object_types, vertical=None):
        seen_hub_ids.append(hub_id)
        return {}

    monkeypatch.setattr(onboarding, "profile_tenant_fields", _recording_profile_fields)

    await produce_onboarding_profile("hub_only_this_one", object_types=["COMPANY"], allow_unqualified=True)

    assert seen_hub_ids == ["hub_only_this_one"]


@pytest.mark.asyncio
async def test_two_tenants_produce_distinctly_scoped_profiles(monkeypatch):
    await _seed_tenant("hub_a", portal_name="Acme Inc")
    await _seed_tenant("hub_b", portal_name="Beta Co")
    _fake_profiled(monkeypatch, {"COMPANY": [FieldProfile("name", True, 1, 1, None)]})

    profile_a = await produce_onboarding_profile("hub_a", object_types=["COMPANY"], allow_unqualified=True)
    profile_b = await produce_onboarding_profile("hub_b", object_types=["COMPANY"], allow_unqualified=True)

    a = await get_profile_for_tenant("hub_a", profile_a)
    b = await get_profile_for_tenant("hub_b", profile_b)

    assert a.name == "Acme Inc"
    assert b.name == "Beta Co"
    assert a.id != b.id


# --- vertical required by default (2026-08-31) ---


@pytest.mark.asyncio
async def test_produce_onboarding_profile_refuses_without_a_vertical(monkeypatch):
    await _seed_tenant("hub_a")
    _fake_profiled(monkeypatch, {"COMPANY": [FieldProfile("name", True, 1, 1, None)]})

    with pytest.raises(ValueError, match="no vertical selected"):
        await produce_onboarding_profile("hub_a", object_types=["COMPANY"])


@pytest.mark.asyncio
async def test_produce_onboarding_profile_resolves_the_tenants_own_vertical_from_postgres(monkeypatch):
    await _seed_tenant("hub_a")
    await set_tenant_vertical("hub_a", "saas")
    _fake_profiled(monkeypatch, {"COMPANY": [FieldProfile("hs_object_source", True, 1, 1, "trust_by_default")]})

    # vertical not passed explicitly — must be resolved from tenants.vertical
    profile_id = await produce_onboarding_profile("hub_a", object_types=["COMPANY"])

    profile = await get_profile_for_tenant("hub_a", profile_id)
    assert profile.vertical == "saas"
    assert profile.fields[0].status == STATUS_CONFIRMED_RELEVANT


@pytest.mark.asyncio
async def test_produce_onboarding_profile_allow_unqualified_bypasses_the_requirement(monkeypatch):
    await _seed_tenant("hub_a")
    _fake_profiled(monkeypatch, {"COMPANY": [FieldProfile("name", True, 1, 1, None)]})

    profile_id = await produce_onboarding_profile(
        "hub_a", object_types=["COMPANY"], allow_unqualified=True
    )

    profile = await get_profile_for_tenant("hub_a", profile_id)
    assert profile.vertical is None
    assert profile.fields[0].status == STATUS_NEEDS_REVIEW


@pytest.mark.asyncio
async def test_produce_onboarding_profile_explicit_vertical_wins_over_postgres(monkeypatch):
    await _seed_tenant("hub_a")
    await set_tenant_vertical("hub_a", "saas")
    _fake_profiled(monkeypatch, {"COMPANY": [FieldProfile("name", True, 1, 1, None)]})

    # Explicit argument takes precedence over the tenant's stored default.
    profile_id = await produce_onboarding_profile("hub_a", object_types=["COMPANY"], vertical="ecommerce")

    profile = await get_profile_for_tenant("hub_a", profile_id)
    assert profile.vertical == "ecommerce"
