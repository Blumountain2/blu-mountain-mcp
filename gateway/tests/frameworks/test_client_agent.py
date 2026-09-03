"""Task 3.5 tests (specs/client-agent-instantiation/spec.md): a client
agent instance is produced from exactly one client's vertical template
plus that client's own onboarding profile, versioned so a new instance
never mutates a prior one, and structurally usable only for the client it
was produced for."""

import pytest

from db import get_pool
from frameworks import onboarding
from frameworks.client_agent import (
    get_instance_for_tenant,
    get_latest_client_agent_instance,
    produce_client_agent_instance,
    resolve_client_agent_instance,
    resolve_template_for_instance,
)
from frameworks.onboarding import produce_onboarding_profile
from frameworks.profiling import FieldProfile
from frameworks.vertical import set_tenant_vertical
from frameworks.vertical_templates import ingest_template


async def _seed_tenant(hub_id: str) -> None:
    pool = await get_pool()
    await pool.execute("INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'installed')", hub_id)


def _fake_profiled(monkeypatch, result: dict):
    async def fake_profile_tenant_fields(hub_id, object_types, vertical=None):
        return result

    monkeypatch.setattr(onboarding, "profile_tenant_fields", fake_profile_tenant_fields)


# --- vertical requirement, matching onboarding's own posture ---


@pytest.mark.asyncio
async def test_produce_instance_refuses_without_a_vertical():
    await _seed_tenant("hub_a")

    with pytest.raises(ValueError):
        await produce_client_agent_instance("hub_a")


@pytest.mark.asyncio
async def test_produce_instance_refuses_clearly_even_with_allow_unqualified():
    # Unlike onboarding.produce_onboarding_profile, there is no unqualified
    # path here: client_agent_instances.vertical_template_id is NOT NULL,
    # so an instance can never be produced without a resolved vertical.
    # Previously this raised an opaque AttributeError ('NoneType' object
    # has no attribute 'id') instead of a clear, actionable ValueError.
    await _seed_tenant("hub_a")

    with pytest.raises(ValueError, match="no vertical selected"):
        await produce_client_agent_instance("hub_a", allow_unqualified=True)


@pytest.mark.asyncio
async def test_produce_instance_refuses_when_verticals_template_does_not_exist_yet():
    await _seed_tenant("hub_a")
    await set_tenant_vertical("hub_a", "saas")
    # Deliberately no ingest_template call — vertical is known but has no
    # template yet.

    with pytest.raises(ValueError):
        await produce_client_agent_instance("hub_a")


@pytest.mark.asyncio
async def test_produce_instance_resolves_the_tenants_own_vertical_from_postgres(monkeypatch):
    await _seed_tenant("hub_a")
    await set_tenant_vertical("hub_a", "ecommerce")
    await ingest_template("ecommerce", "ecommerce additions")
    _fake_profiled(monkeypatch, {})

    instance_id = await produce_client_agent_instance("hub_a")
    instance = await get_instance_for_tenant("hub_a", instance_id)
    template = await resolve_template_for_instance(instance)

    assert template.vertical == "ecommerce"


# --- versioning: a new instance never mutates a prior one ---


@pytest.mark.asyncio
async def test_a_new_instance_version_does_not_alter_the_prior_one(monkeypatch):
    await _seed_tenant("hub_a")
    await set_tenant_vertical("hub_a", "saas")
    await ingest_template("saas", "additions")
    _fake_profiled(monkeypatch, {})

    first_id = await produce_client_agent_instance("hub_a")
    second_id = await produce_client_agent_instance("hub_a")

    assert second_id != first_id
    first = await get_instance_for_tenant("hub_a", first_id)
    second = await get_instance_for_tenant("hub_a", second_id)
    assert first.version == 1
    assert second.version == 2

    latest = await get_latest_client_agent_instance("hub_a")
    assert latest.id == second_id


@pytest.mark.asyncio
async def test_duplicate_hub_id_and_version_is_rejected_at_the_db_level(monkeypatch):
    # next_version()'s SELECT MAX(version)+1 has no locking of its own —
    # this UNIQUE constraint is the backstop that turns a race into a
    # loud DB error instead of two ambiguous rows silently coexisting,
    # matching vertical_agent_templates' and analysis_content's own
    # UNIQUE constraints on the equivalent shape.
    import asyncpg

    await _seed_tenant("hub_a")
    await set_tenant_vertical("hub_a", "saas")
    await ingest_template("saas", "additions")
    _fake_profiled(monkeypatch, {})

    first_id = await produce_client_agent_instance("hub_a")
    first = await get_instance_for_tenant("hub_a", first_id)

    pool = await get_pool()
    with pytest.raises(asyncpg.UniqueViolationError):
        await pool.execute(
            "INSERT INTO client_agent_instances (hub_id, vertical_template_id, version, injected_documentation) "
            "VALUES ($1, $2, $3, $4)",
            "hub_a",
            first.vertical_template_id,
            first.version,
            "duplicate",
        )


# --- structural isolation ---


@pytest.mark.asyncio
async def test_a_wrong_hub_id_cannot_retrieve_another_clients_instance(monkeypatch):
    await _seed_tenant("hub_a")
    await _seed_tenant("hub_b")
    await set_tenant_vertical("hub_a", "saas")
    await ingest_template("saas", "additions")
    _fake_profiled(monkeypatch, {})

    instance_id = await produce_client_agent_instance("hub_a")

    assert await get_instance_for_tenant("hub_b", instance_id) is None


@pytest.mark.asyncio
async def test_producing_one_clients_instance_never_reads_another_tenants_data(monkeypatch):
    await _seed_tenant("hub_a")
    await _seed_tenant("hub_b")
    await set_tenant_vertical("hub_a", "saas")
    await set_tenant_vertical("hub_b", "saas")
    await ingest_template("saas", "additions")

    _fake_profiled(monkeypatch, {"CONTACT": [FieldProfile("email", True, 1, 1, "trust_by_default")]})
    await produce_onboarding_profile("hub_a", object_types=["CONTACT"], allow_unqualified=True)
    # hub_b deliberately has no onboarding profile.

    instance_id = await produce_client_agent_instance("hub_b")
    instance = await get_instance_for_tenant("hub_b", instance_id)

    assert "email" not in instance.injected_documentation
    assert "No onboarding profile exists yet" in instance.injected_documentation


@pytest.mark.asyncio
async def test_two_clients_of_the_same_vertical_get_distinctly_scoped_instances(monkeypatch):
    await _seed_tenant("hub_a")
    await _seed_tenant("hub_b")
    await set_tenant_vertical("hub_a", "saas")
    await set_tenant_vertical("hub_b", "saas")
    await ingest_template("saas", "shared additions")

    _fake_profiled(monkeypatch, {"COMPANY": [FieldProfile("total_revenue", True, 1, 1, "trust_by_default")]})
    await produce_onboarding_profile("hub_a", object_types=["COMPANY"], allow_unqualified=True)
    id_a = await produce_client_agent_instance("hub_a")

    _fake_profiled(monkeypatch, {"DEAL": [FieldProfile("amount", True, 1, 1, "unreliable_by_default")]})
    await produce_onboarding_profile("hub_b", object_types=["DEAL"], allow_unqualified=True)
    id_b = await produce_client_agent_instance("hub_b")

    instance_a = await get_instance_for_tenant("hub_a", id_a)
    instance_b = await get_instance_for_tenant("hub_b", id_b)

    # Same vertical template...
    assert instance_a.vertical_template_id == instance_b.vertical_template_id
    # ...but genuinely different injected documentation.
    assert instance_a.injected_documentation != instance_b.injected_documentation
    assert "total_revenue" in instance_a.injected_documentation
    assert "total_revenue" not in instance_b.injected_documentation
    assert "amount" in instance_b.injected_documentation
    assert "amount" not in instance_a.injected_documentation


# --- resolve_client_agent_instance: get-or-create ---


@pytest.mark.asyncio
async def test_resolve_produces_an_instance_when_none_exists_yet(monkeypatch):
    await _seed_tenant("hub_a")
    await set_tenant_vertical("hub_a", "saas")
    await ingest_template("saas", "additions")
    _fake_profiled(monkeypatch, {})

    resolved = await resolve_client_agent_instance("hub_a")

    assert resolved.version == 1
    assert await get_latest_client_agent_instance("hub_a") is not None


@pytest.mark.asyncio
async def test_resolve_returns_the_existing_instance_without_producing_a_new_one(monkeypatch):
    await _seed_tenant("hub_a")
    await set_tenant_vertical("hub_a", "saas")
    await ingest_template("saas", "additions")
    _fake_profiled(monkeypatch, {})

    first = await resolve_client_agent_instance("hub_a")
    second = await resolve_client_agent_instance("hub_a")

    assert first.id == second.id
    assert second.version == 1  # no second row was produced
