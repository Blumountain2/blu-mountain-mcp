"""Task 1.4: proves stored content is reusable unmodified across reads,
and that a new version never alters an already-produced reference to an
earlier one (specs/analysis-template-schema/spec.md's versioning
requirement)."""

import pytest

from frameworks import CONTENT_TYPE_FRAMEWORK, CONTENT_TYPE_SKILL, get_latest, get_version, ingest, list_latest


@pytest.mark.asyncio
async def test_ingest_first_version_is_one():
    version = await ingest(CONTENT_TYPE_FRAMEWORK, "saas", "v1 content", source_path="test.md")
    assert version == 1


@pytest.mark.asyncio
async def test_ingest_second_version_increments_and_keeps_first_intact():
    await ingest(CONTENT_TYPE_FRAMEWORK, "saas", "v1 content")
    v2 = await ingest(CONTENT_TYPE_FRAMEWORK, "saas", "v2 content")

    assert v2 == 2
    first = await get_version(CONTENT_TYPE_FRAMEWORK, "saas", 1)
    assert first.content == "v1 content"


@pytest.mark.asyncio
async def test_updating_to_a_new_version_does_not_alter_the_earlier_one():
    # Directly exercises the spec scenario: "a tenant's configuration
    # already instantiated from version 1 continues to read as it did
    # before the update" — a caller holding version=1 must see identical
    # content before and after a v2 ingest.
    await ingest(CONTENT_TYPE_FRAMEWORK, "plg", "original")
    before = await get_version(CONTENT_TYPE_FRAMEWORK, "plg", 1)

    await ingest(CONTENT_TYPE_FRAMEWORK, "plg", "revised")
    after = await get_version(CONTENT_TYPE_FRAMEWORK, "plg", 1)

    assert before.content == after.content == "original"


@pytest.mark.asyncio
async def test_get_latest_returns_the_newest_version():
    await ingest(CONTENT_TYPE_FRAMEWORK, "marketplace", "old")
    await ingest(CONTENT_TYPE_FRAMEWORK, "marketplace", "new")

    latest = await get_latest(CONTENT_TYPE_FRAMEWORK, "marketplace")
    assert latest.version == 2
    assert latest.content == "new"


@pytest.mark.asyncio
async def test_reading_the_same_content_twice_is_identical_and_read_only():
    await ingest(CONTENT_TYPE_FRAMEWORK, "ecommerce", "stable content")

    first_read = await get_latest(CONTENT_TYPE_FRAMEWORK, "ecommerce")
    second_read = await get_latest(CONTENT_TYPE_FRAMEWORK, "ecommerce")

    assert first_read == second_read


@pytest.mark.asyncio
async def test_get_latest_returns_none_for_unknown_name():
    assert await get_latest(CONTENT_TYPE_FRAMEWORK, "does-not-exist") is None


@pytest.mark.asyncio
async def test_skill_is_retrievable_independent_of_any_vertical():
    await ingest(CONTENT_TYPE_SKILL, "account-diagnostic-skill", "skill instructions")

    result = await get_latest(CONTENT_TYPE_SKILL, "account-diagnostic-skill")

    assert result is not None
    assert result.content == "skill instructions"


@pytest.mark.asyncio
async def test_two_verticals_share_no_state():
    await ingest(CONTENT_TYPE_FRAMEWORK, "saas", "saas content")
    await ingest(CONTENT_TYPE_FRAMEWORK, "transactional", "transactional content")

    saas = await get_latest(CONTENT_TYPE_FRAMEWORK, "saas")
    transactional = await get_latest(CONTENT_TYPE_FRAMEWORK, "transactional")

    assert saas.content == "saas content"
    assert transactional.content == "transactional content"


@pytest.mark.asyncio
async def test_list_latest_returns_one_row_per_name_at_its_newest_version():
    await ingest(CONTENT_TYPE_FRAMEWORK, "saas", "v1")
    await ingest(CONTENT_TYPE_FRAMEWORK, "saas", "v2")
    await ingest(CONTENT_TYPE_FRAMEWORK, "plg", "only version")

    results = await list_latest(CONTENT_TYPE_FRAMEWORK)
    by_name = {r.name: r for r in results}

    assert by_name["saas"].version == 2
    assert by_name["saas"].content == "v2"
    assert by_name["plg"].version == 1


@pytest.mark.asyncio
async def test_unrecognized_content_type_is_rejected():
    with pytest.raises(ValueError):
        await ingest("not-a-real-type", "saas", "content")
