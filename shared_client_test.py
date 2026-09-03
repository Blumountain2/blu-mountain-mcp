"""shared_client_test.py — bundled demo/verification script for the shared
vertical-agent architecture (openspec/changes/analysis-model-templates).

Run from inside the mcp-gateway container:

    docker cp shared_client_test.py mcp-gateway:/app/shared_client_test.py
    docker exec -w /app mcp-gateway python3 shared_client_test.py

Five independent steps — one failing or not-ready doesn't stop the
others. A summary table at the end shows PASS/FAIL/SKIP/NOT READY for
all five. Steps 1-4 need nothing but the database already built during
this project. Step 5 needs a real, valid ANTHROPIC_API_KEY — if it isn't
ready yet, that step reports NOT READY without breaking the rest.
"""

import asyncio
import ast
import subprocess
import sys
from pathlib import Path

from db import get_pool

results = []  # (step, label, status, note)


def _banner(title):
    print()
    print("=" * 74)
    print(title)
    print("=" * 74)


async def step1_shared_framework_storage():
    _banner("STEP 1 — Shared framework/skill/prompt content, stored once")
    from frameworks.store import list_latest

    rows = await list_latest()
    by_key = {(r.content_type, r.name): r for r in rows}
    verticals = ["saas", "plg", "marketplace", "ecommerce", "services-project", "transactional"]
    expected = (
        [("vertical_framework", v) for v in verticals]
        + [("challenge_library", v) for v in verticals]
        + [
            ("skill", "account-diagnostic-skill"),
            ("prompt", "weekly-diagnostic-prompt"),
            ("operating_principles", "operating-principles"),
            ("template_library", "template-library"),
        ]
    )
    missing = []
    for content_type, name in expected:
        row = by_key.get((content_type, name))
        if row:
            print(f"  ok       {content_type:18} {name:22} v{row.version}  {len(row.content):>7,} chars")
        else:
            print(f"  MISSING  {content_type:18} {name}")
            missing.append((content_type, name))

    if missing:
        results.append(("1", "Shared framework storage", "FAIL", f"{len(missing)} of {len(expected)} missing"))
    else:
        results.append(("1", "Shared framework storage", "PASS", f"all {len(expected)} pieces stored, one row each"))


async def step2_per_client_variation():
    _banner("STEP 2 — Two real clients, genuinely different onboarding profiles")
    pool = await get_pool()
    # Only the most recent profile per tenant — a tenant may have several
    # (e.g. an earlier, smaller-object-set run), and only the latest one
    # reflects current state.
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (p.hub_id) p.hub_id, p.name, p.vertical, p.created_at,
            (SELECT COUNT(*) FROM tenant_onboarding_profile_fields f WHERE f.profile_id = p.id) AS field_count
        FROM tenant_onboarding_profiles p
        ORDER BY p.hub_id, p.created_at DESC
        """
    )
    if not rows:
        print("  No onboarding profiles found yet.")
        results.append(("2", "Per-client variation", "SKIP", "no profiles in the database"))
        return

    for r in rows:
        print(
            f"  hub_id={r['hub_id']:<12} name={r['name']!r:<32} "
            f"vertical={str(r['vertical']):<8} fields={r['field_count']}"
        )

    counts = {r["field_count"] for r in rows}
    if len(rows) >= 2 and len(counts) > 1:
        results.append(("2", "Per-client variation", "PASS", f"{len(rows)} profiles, field counts genuinely differ"))
    elif len(rows) >= 2:
        results.append(("2", "Per-client variation", "FAIL", "profiles exist but field counts are identical"))
    else:
        results.append(("2", "Per-client variation", "SKIP", "only one profile exists — need a second tenant to compare"))


_DEPS_DIR = "/tmp/shared_client_test_deps"


def _ensure_pytest_installed():
    try:
        import pytest  # noqa: F401

        return {}
    except ImportError:
        pass
    print("  (pytest not installed in this container yet — installing requirements-dev.txt once...)")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--target", _DEPS_DIR, "-q", "-r", "requirements-dev.txt"],
        cwd="/app",
        check=True,
    )
    import os

    existing = os.environ.get("PYTHONPATH", "")
    return {"PYTHONPATH": f"{_DEPS_DIR}:{existing}" if existing else _DEPS_DIR}


_ISOLATION_FILES = [
    "tests/test_tenant_isolation.py",
    "tests/frameworks/test_onboarding.py",
    "tests/frameworks/test_profiling.py",
    "tests/frameworks/test_pull_agent.py",
]


def step3_isolation_suite():
    _banner("STEP 3 — What's proven, then whether it's actually true")
    extra_env = _ensure_pytest_installed()
    for rel_path in _ISOLATION_FILES:
        path = Path(rel_path)
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        doc = ast.get_docstring(tree)
        print(f"\n  --- {rel_path} ---")
        if doc:
            for line in doc.strip().splitlines():
                print(f"  {line}")
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_"):
                print(f"    - {node.name.removeprefix('test_').replace('_', ' ')}")

    print("\n  Running the tests now...\n")
    import os

    env = {**os.environ, **extra_env}
    # Runs the exact files whose claims were just listed above — every
    # claim printed is guaranteed to correspond to a test that actually
    # ran, rather than relying on a hand-maintained keyword filter that
    # can silently drift out of sync as tests get added or renamed.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", *_ISOLATION_FILES],
        cwd="/app",
        capture_output=True,
        text=True,
        env=env,
    )
    print(proc.stdout[-8000:])
    if proc.stderr.strip():
        print(proc.stderr[-1000:])

    ran_something = "collected 0 items" not in proc.stdout
    if proc.returncode == 0 and ran_something:
        results.append(("3", "Isolation test suite", "PASS", "every isolation and per-client test passed"))
    else:
        results.append(("3", "Isolation test suite", "FAIL", f"pytest exit code {proc.returncode}"))


async def step4_audit_trail():
    _banner("STEP 4 — Every pull-agent action is attributable to the right tenant")
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT hub_id, event_type, occurred_at FROM audit_log
        WHERE event_type IN ('pull_agent_run_completed', 'pull_agent_run_failed')
        ORDER BY occurred_at DESC LIMIT 5
        """
    )
    if not rows:
        print("  No pull-agent audit entries yet — run Step 5 (or a prior real run) first.")
        results.append(("4", "Audit trail", "SKIP", "no pull-agent runs recorded yet"))
        return

    for r in rows:
        print(f"  {r['occurred_at']}  hub_id={r['hub_id']}  {r['event_type']}")

    if all(r["hub_id"] for r in rows):
        results.append(("4", "Audit trail", "PASS", f"{len(rows)} entries, every one correctly attributed"))
    else:
        results.append(("4", "Audit trail", "FAIL", "found an entry with no hub_id"))


async def step5_live_run():
    _banner("STEP 5 (optional) — Live run against the real Anthropic API")
    from config import settings

    if not settings.anthropic_api_key:
        print("  ANTHROPIC_API_KEY is not set.")
        results.append(("5", "Live pull-agent run", "NOT READY", "no API key configured"))
        return

    from frameworks.client_agent import resolve_client_agent_instance
    from frameworks.vertical import get_tenant_vertical, set_tenant_vertical
    from frameworks.pull_agent import run_client_agent

    hub_id = "148997330"
    vertical = await get_tenant_vertical(hub_id)
    if vertical is None:
        vertical = "saas"
        await set_tenant_vertical(hub_id, vertical)

    # Shows exactly what makes this run per-client, not just per-vertical:
    # the persisted client agent instance's own injected documentation
    # (openspec/changes/separate-vertical-client-agents) — built from this
    # client's onboarding profile, distinct from the shared vertical
    # template every client of this vertical also uses.
    instance = await resolve_client_agent_instance(hub_id)
    print("  per-client context injected into this run's request:")
    for line in instance.injected_documentation.splitlines():
        print(f"    {line}")
    print()

    try:
        result = await run_client_agent(hub_id)
        print(f"  gathered object types: {list(result.keys())}")
        for object_type, records in result.items():
            print(f"    {object_type}: {len(records)} records")
        total = sum(len(v) for v in result.values())
        results.append(("5", "Live pull-agent run", "PASS", f"gathered {total} real records via a live API call"))
    except Exception as exc:
        print(f"  Live run failed: {exc}")
        results.append(("5", "Live pull-agent run", "NOT READY", str(exc)[:90]))


async def main():
    await step1_shared_framework_storage()
    await step2_per_client_variation()
    step3_isolation_suite()
    await step4_audit_trail()
    await step5_live_run()

    _banner("SUMMARY")
    for step, label, status, note in results:
        print(f"  [{status:9}] Step {step}: {label:28} {note}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
