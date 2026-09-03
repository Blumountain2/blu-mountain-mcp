"""Task 1.4 / 2.3 (openspec/changes/separate-vertical-client-agents):
proves vertical agent template versioning mirrors analysis_content's
proven pattern exactly — updating one vertical's template never alters
another vertical's, and a prior version stays retrievable after a new one
is created — plus that a template never embeds client-specific data."""

import pytest

from frameworks.vertical_templates import (
    get_latest_template,
    get_template_by_id,
    get_template_version,
    ingest_template,
    list_latest_templates,
)


@pytest.mark.asyncio
async def test_ingest_first_version_is_one():
    version = await ingest_template("saas", "v1 additions")
    assert version == 1


@pytest.mark.asyncio
async def test_ingest_second_version_increments_and_keeps_first_intact():
    await ingest_template("saas", "v1 additions")
    v2 = await ingest_template("saas", "v2 additions")

    assert v2 == 2
    first = await get_template_version("saas", 1)
    assert first.system_prompt_additions == "v1 additions"


@pytest.mark.asyncio
async def test_updating_one_vertical_never_alters_another():
    await ingest_template("saas", "saas additions")
    await ingest_template("plg", "plg additions")

    await ingest_template("saas", "saas additions v2")

    plg = await get_latest_template("plg")
    assert plg.version == 1
    assert plg.system_prompt_additions == "plg additions"


@pytest.mark.asyncio
async def test_a_prior_version_stays_retrievable_after_a_new_one_is_created():
    await ingest_template("saas", "original")
    await ingest_template("saas", "revised")

    original = await get_template_version("saas", 1)
    latest = await get_latest_template("saas")

    assert original.system_prompt_additions == "original"
    assert latest.version == 2
    assert latest.system_prompt_additions == "revised"


@pytest.mark.asyncio
async def test_get_latest_returns_none_for_a_vertical_with_no_template_yet():
    assert await get_latest_template("plg") is None


@pytest.mark.asyncio
async def test_unrecognized_vertical_is_rejected():
    with pytest.raises(ValueError):
        await ingest_template("not-a-real-vertical", "additions")


@pytest.mark.asyncio
async def test_list_latest_templates_returns_one_row_per_vertical_at_its_newest_version():
    await ingest_template("saas", "v1")
    await ingest_template("saas", "v2")
    await ingest_template("plg", "only version")

    results = await list_latest_templates()
    by_vertical = {t.vertical: t for t in results}

    assert by_vertical["saas"].version == 2
    assert by_vertical["saas"].system_prompt_additions == "v2"
    assert by_vertical["plg"].version == 1


@pytest.mark.asyncio
async def test_tool_config_round_trips_as_a_dict():
    await ingest_template("saas", "additions", tool_config={"max_tool_calls": 5})

    latest = await get_latest_template("saas")

    assert latest.tool_config == {"max_tool_calls": 5}


@pytest.mark.asyncio
async def test_tool_config_defaults_to_empty_dict():
    await ingest_template("saas", "additions")

    latest = await get_latest_template("saas")

    assert latest.tool_config == {}


@pytest.mark.asyncio
async def test_get_template_by_id_matches_get_latest():
    await ingest_template("saas", "additions")
    latest = await get_latest_template("saas")

    by_id = await get_template_by_id(latest.id)

    assert by_id == latest


@pytest.mark.asyncio
async def test_a_vertical_template_never_embeds_client_specific_data():
    # Structural, not just conventional: ingest_template's signature has no
    # hub_id/client parameter at all, so a caller cannot embed one even by
    # mistake — this test documents and locks that shape rather than
    # asserting on stored content.
    import inspect

    params = inspect.signature(ingest_template).parameters
    assert "hub_id" not in params
    assert "client" not in params
    assert "tenant" not in params
