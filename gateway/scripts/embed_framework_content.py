"""Regenerates each vertical's FRAMEWORK_TEXT and the shared
OPERATIONAL_SKILL_TEXT/RUNTIME_PROMPT_TEXT constants from Blu Mountain's
real, delivered documents (openspec/changes/vertical-framework-content-
in-code) — the maintenance counterpart to frameworks/ingest.py, for the
content this project now bakes into the agent hierarchy's own Python
files instead of reading from Postgres at request time.

Run this whenever Blu Mountain delivers a revised framework, operational
skill, or runtime prompt document. It overwrites `gateway/frameworks/
agents/verticals/*.py` and `gateway/frameworks/agents/content.py`
in place; review the diff with git before committing, the same as any
other generated-file change. An existing vertical file's SYSTEM_PROMPT_
ADDITIONS is preserved across a regeneration — only FRAMEWORK_TEXT and
the surrounding docstring/imports are rewritten.

    cd gateway && python3 scripts/embed_framework_content.py \\
        --source-dir "../context/Blu Mountain Documentation"

After running, always re-run the full test suite (frameworks_agents
tests read these embedded constants directly) and, before committing,
gateway/scripts/live_verification.py against a real portal to confirm
the new content still produces a real, sensible diagnostic report.
"""

import argparse
import ast
import pathlib

FRAMEWORK_FILES = {
    "saas": ("SaaSAgent", "saas.py", "Artifacts/SaaS_Vertical_Framework_v2.md", "SaaS"),
    "plg": ("PLGAgent", "plg.py", "Artifacts/PLG_Vertical_Framework.md", "PLG"),
    "marketplace": (
        "MarketplaceAgent",
        "marketplace.py",
        "Artifacts/Marketplace_Vertical_Framework.md",
        "Marketplace",
    ),
    "ecommerce": ("EcommerceAgent", "ecommerce.py", "Artifacts/Ecommerce_Vertical_Framework.md", "E-commerce"),
    "services-project": (
        "ServicesProjectAgent",
        "services_project.py",
        "Artifacts/Services_Project_Vertical_Framework.md",
        "Services/Project",
    ),
    "transactional": (
        "TransactionalAgent",
        "transactional.py",
        "Artifacts/Transactional_Vertical_Framework (1).md",
        "Transactional",
    ),
}

SKILL_RELATIVE_PATH = "Skills/account-diagnostic-SKILL.md"
PROMPT_RELATIVE_PATH = "Prompts/Weekly_Diagnostic_Prompt.md"

VERTICALS_DIR = pathlib.Path(__file__).resolve().parent.parent / "frameworks" / "agents" / "verticals"
CONTENT_PY = pathlib.Path(__file__).resolve().parent.parent / "frameworks" / "agents" / "content.py"

VERTICAL_TEMPLATE = '''from ..base import BaseAgent


class {class_name}(BaseAgent):
    """{vertical_label} vertical agent. FRAMEWORK_TEXT below is Blu
    Mountain's own real, delivered {vertical_label} framework document,
    embedded verbatim as a Python string constant (openspec/changes/
    vertical-framework-content-in-code) rather than read from Postgres at
    request time via frameworks.store.get_latest() — eliminating the
    "someone forgot to run frameworks.ingest" failure mode entirely, at
    the cost of this content now living in git/the built image (a
    deliberate, explicit tradeoff — see that change's design.md).

    Regenerate this file with scripts/embed_framework_content.py when
    Blu Mountain delivers a revised {vertical_label} framework document —
    never hand-edit FRAMEWORK_TEXT directly."""

    VERTICAL = "{vertical}"
    SYSTEM_PROMPT_ADDITIONS = {system_prompt_additions!r}

    FRAMEWORK_TEXT = r"""{content}"""
'''

CONTENT_PY_TEMPLATE = '''"""Shared, vertical-agnostic content embedded verbatim as Python string
constants (openspec/changes/vertical-framework-content-in-code) — Blu
Mountain's own real, delivered operational skill and runtime prompt,
unchanged from what was previously read from Postgres via
frameworks.store.get_latest(CONTENT_TYPE_SKILL/CONTENT_TYPE_PROMPT, ...).
Both are shared across every vertical (one real skill, one real prompt),
so they live here once rather than duplicated into all six vertical
files.

RUNTIME_PROMPT_TEXT still contains the literal "{{CLIENT_NAME}}" and
"{{VERTICAL_FRAMEWORK_NAME}}" placeholders diagnostics.py substitutes at
render time.

Regenerate this file with scripts/embed_framework_content.py when Blu
Mountain delivers a revised operational skill or runtime prompt document
— never hand-edit these constants directly.
"""

OPERATIONAL_SKILL_TEXT = r"""{skill_content}"""

RUNTIME_PROMPT_TEXT = r"""{prompt_content}"""
'''


def _existing_system_prompt_additions(dest: pathlib.Path) -> str:
    """Reads back a vertical file's current SYSTEM_PROMPT_ADDITIONS value,
    if the file already exists, so a regeneration never silently discards
    a human-authored addition — only FRAMEWORK_TEXT is meant to change
    when this script re-runs."""
    if not dest.is_file():
        return ""
    tree = ast.parse(dest.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SYSTEM_PROMPT_ADDITIONS" for t in node.targets
        ):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    return ""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source-dir",
        required=True,
        type=pathlib.Path,
        help='Path to the delivered documentation directory (e.g. "context/Blu Mountain Documentation")',
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    source_dir: pathlib.Path = args.source_dir

    for vertical, (class_name, filename, relative_path, vertical_label) in FRAMEWORK_FILES.items():
        source_path = source_dir / relative_path
        if not source_path.is_file():
            raise FileNotFoundError(f"Missing expected file: {source_path}")
        content = source_path.read_text(encoding="utf-8")
        dest = VERTICALS_DIR / filename
        existing_additions = _existing_system_prompt_additions(dest)
        rendered = VERTICAL_TEMPLATE.format(
            class_name=class_name,
            vertical=vertical,
            vertical_label=vertical_label,
            system_prompt_additions=existing_additions,
            content=content,
        )
        dest.write_text(rendered, encoding="utf-8")
        print(f"wrote {dest} ({len(content)} chars embedded)")

    skill_path = source_dir / SKILL_RELATIVE_PATH
    prompt_path = source_dir / PROMPT_RELATIVE_PATH
    for path in (skill_path, prompt_path):
        if not path.is_file():
            raise FileNotFoundError(f"Missing expected file: {path}")

    skill_content = skill_path.read_text(encoding="utf-8")
    prompt_content = prompt_path.read_text(encoding="utf-8")
    rendered = CONTENT_PY_TEMPLATE.format(skill_content=skill_content, prompt_content=prompt_content)
    CONTENT_PY.write_text(rendered, encoding="utf-8")
    print(f"wrote {CONTENT_PY} (skill {len(skill_content)} chars, prompt {len(prompt_content)} chars)")


if __name__ == "__main__":
    main()
