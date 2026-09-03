"""Tests for the FILE_MAP -> storage ingestion pipeline, using synthetic
files under a temp directory — never the real gitignored client
documentation, which these tests must not depend on existing."""

import pytest

from frameworks import FILE_MAP, get_latest, ingest_directory


def _write_fixture_tree(root):
    for rel_path in FILE_MAP:
        full_path = root / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(f"content for {rel_path}", encoding="utf-8")


@pytest.mark.asyncio
async def test_ingest_directory_ingests_every_mapped_file(tmp_path):
    _write_fixture_tree(tmp_path)

    results = await ingest_directory(tmp_path)

    assert set(results.keys()) == set(FILE_MAP.keys())
    assert all(version == 1 for version in results.values())


@pytest.mark.asyncio
async def test_ingest_directory_content_is_readable_afterward(tmp_path):
    _write_fixture_tree(tmp_path)

    await ingest_directory(tmp_path)

    content_type, name = FILE_MAP["Skills/account-diagnostic-SKILL.md"]
    stored = await get_latest(content_type, name)
    assert stored.content == "content for Skills/account-diagnostic-SKILL.md"
    assert stored.source_path == "Skills/account-diagnostic-SKILL.md"


@pytest.mark.asyncio
async def test_ingest_directory_fails_loudly_on_missing_file_without_partial_ingest(tmp_path):
    _write_fixture_tree(tmp_path)
    # Remove one expected file so the directory is incomplete.
    missing_rel = next(iter(FILE_MAP))
    (tmp_path / missing_rel).unlink()

    with pytest.raises(FileNotFoundError):
        await ingest_directory(tmp_path)

    # Nothing should have been ingested — a silent "7 of 8" partial
    # ingest would be a confusing gap, not a useful degraded state.
    another_rel = next(k for k in FILE_MAP if k != missing_rel)
    content_type, name = FILE_MAP[another_rel]
    assert await get_latest(content_type, name) is None
