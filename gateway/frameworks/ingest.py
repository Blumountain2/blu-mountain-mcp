"""Maps Blu Mountain's delivered documentation files (converted to
Markdown, verified word-for-word complete against the original .docx/.xlsx
before those originals were removed — see context/BUILD_COMPARISON.md) to
this project's (content_type, name) addressing, and ingests them via
frameworks.store.ingest().

This module contains no client content itself, only the mapping and the
ingestion logic — the actual files live under the gitignored
"context/Blu Mountain Documentation/" directory and are supplied at run
time via --source-dir, never baked into this repo or its container image.
"""

import argparse
import asyncio
from pathlib import Path

import structlog

from .store import (
    CONTENT_TYPE_CHALLENGE_LIBRARY,
    CONTENT_TYPE_FRAMEWORK,
    CONTENT_TYPE_OPERATING_PRINCIPLES,
    CONTENT_TYPE_PROMPT,
    CONTENT_TYPE_SKILL,
    CONTENT_TYPE_TEMPLATE_LIBRARY,
    ingest,
)

logger = structlog.get_logger()

# relative path (from the source directory root) -> (content_type, name)
FILE_MAP: dict[str, tuple[str, str]] = {
    "Artifacts/SaaS_Vertical_Framework_v2.md": (CONTENT_TYPE_FRAMEWORK, "saas"),
    "Artifacts/PLG_Vertical_Framework.md": (CONTENT_TYPE_FRAMEWORK, "plg"),
    "Artifacts/Marketplace_Vertical_Framework.md": (CONTENT_TYPE_FRAMEWORK, "marketplace"),
    "Artifacts/Ecommerce_Vertical_Framework.md": (CONTENT_TYPE_FRAMEWORK, "ecommerce"),
    "Artifacts/Services_Project_Vertical_Framework.md": (CONTENT_TYPE_FRAMEWORK, "services-project"),
    "Artifacts/Transactional_Vertical_Framework (1).md": (CONTENT_TYPE_FRAMEWORK, "transactional"),
    "Skills/account-diagnostic-SKILL.md": (CONTENT_TYPE_SKILL, "account-diagnostic-skill"),
    "Prompts/Weekly_Diagnostic_Prompt.md": (CONTENT_TYPE_PROMPT, "weekly-diagnostic-prompt"),
    # Added task 7.1 — same naming convention as the frameworks above, one
    # Challenge Library per vertical.
    "Skills/SaaS_Challenge_Library_Skill.md": (CONTENT_TYPE_CHALLENGE_LIBRARY, "saas"),
    "Skills/PLG_Challenge_Library_Skill.md": (CONTENT_TYPE_CHALLENGE_LIBRARY, "plg"),
    "Skills/Marketplace_Challenge_Library_Skill.md": (CONTENT_TYPE_CHALLENGE_LIBRARY, "marketplace"),
    "Skills/Ecommerce_Challenge_Library_Skill.md": (CONTENT_TYPE_CHALLENGE_LIBRARY, "ecommerce"),
    "Skills/Services_Challenge_Library_Skill.md": (CONTENT_TYPE_CHALLENGE_LIBRARY, "services-project"),
    "Skills/Transactional_Challenge_Library_Skill.md": (CONTENT_TYPE_CHALLENGE_LIBRARY, "transactional"),
    "Artifacts/Blu_Operating_Principles.md": (CONTENT_TYPE_OPERATING_PRINCIPLES, "operating-principles"),
    "Artifacts/BluMountain_Template_Library_v1_3.md": (CONTENT_TYPE_TEMPLATE_LIBRARY, "template-library"),
}


async def ingest_directory(source_dir: Path) -> dict[str, int]:
    """Ingests every file in FILE_MAP found under source_dir. Returns
    {relative_path: new_version} for each file actually ingested. Raises
    FileNotFoundError immediately, without ingesting anything, if any
    expected file is missing — a partial ingest of "7 of 8" would be a
    silent, confusing gap, not a useful degraded state."""
    missing = [rel for rel in FILE_MAP if not (source_dir / rel).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing expected file(s) under {source_dir}: {missing}")

    results: dict[str, int] = {}
    for rel_path, (content_type, name) in FILE_MAP.items():
        full_path = source_dir / rel_path
        content = full_path.read_text(encoding="utf-8")
        version = await ingest(content_type, name, content, source_path=rel_path)
        results[rel_path] = version
        logger.info("frameworks.ingest_directory.file_ingested", path=rel_path, name=name, version=version)
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        required=True,
        type=Path,
        help='Path to the delivered documentation directory (e.g. "context/Blu Mountain Documentation")',
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    results = asyncio.run(ingest_directory(args.source_dir))
    for rel_path, version in results.items():
        print(f"{rel_path} -> version {version}")


if __name__ == "__main__":
    main()
