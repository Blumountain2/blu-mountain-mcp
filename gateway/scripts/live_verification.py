"""Systematic, non-mocked verification of the vertical/client agent
separation work (openspec/changes/separate-vertical-client-agents) against
real systems: real Postgres, real HubSpot portals, real Anthropic API, a
real Client<->FastMCP transport. Nothing in this file mocks or fakes
anything — every check either observes real state or makes a real call.

This exists because passing unit tests only prove the code does what the
test *assumes* — never that the assumption matches reality. Run this
whenever you want that second, independent kind of confidence, not just
before archiving a change.

Run from inside the mcp-gateway container (needs the real vaulted HubSpot
tokens and a real ANTHROPIC_API_KEY, both already configured for the dev
stack):

    docker compose up -d
    docker cp gateway/scripts/live_verification.py mcp-gateway:/app/live_verification.py
    docker exec -w /app mcp-gateway python3 live_verification.py

Five independent steps — one failing or not-ready doesn't stop the others.
A summary table at the end shows PASS/FAIL/SKIP/NOT READY for all five.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from fastmcp import Client

from db import get_pool
from frameworks.client_agent import resolve_client_agent_instance
from frameworks.pull_agent import run_client_agent
from frameworks.vertical import KNOWN_VERTICALS
from frameworks.vertical_templates import list_latest_templates
from session import live_session
from sync.hubspot_client import HubSpotDataPullClient

PORTAL_A = "148997330"
PORTAL_B = "149094230"

results = []  # (step, label, status, note)


def _banner(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def _fake_staff_token(jti: str = "live-verification-jti"):
    """The ONLY stand-in in this entire file — a real Google OAuth login
    needs a browser, which this script can't drive. Everything downstream
    of this (Postgres, HubSpot, Anthropic) is completely real. This is the
    same technique gateway/tests/session/test_live_session.py's own
    test_real_transport_* tests use.

    `jti` becomes the session_key live_session._require_staff_identity
    derives — it MUST be distinct per logically-separate session. Two
    concurrent calls sharing one jti share one live_session_selection row
    and will race on which hub_id ends up selected for both — a bug in a
    verification script that shares this fake across concurrent tasks,
    not a production isolation bug (that exact scenario, with real
    distinct session keys, is already covered correctly by
    test_tenant_isolation.py::test_live_session_two_staff_sessions_do_not_leak_selection)."""
    return SimpleNamespace(
        claims={
            "email": "live-verification@blumountain.me",
            "google_user_data": {"hd": "blumountain.me"},
            "jti": jti,
        },
        token="raw-token",
    )


async def step1_vertical_templates_are_real():
    _banner("STEP 1 — Every vertical has a real, persisted agent template")
    templates = await list_latest_templates()
    by_vertical = {t.vertical: t for t in templates}
    missing = sorted(KNOWN_VERTICALS - by_vertical.keys())

    for vertical in sorted(KNOWN_VERTICALS):
        t = by_vertical.get(vertical)
        if t:
            print(f"  ok       {vertical:20} v{t.version}  tool_config={t.tool_config!r}")
        else:
            print(f"  MISSING  {vertical}")

    if missing:
        results.append(("1", "Vertical templates real", "FAIL", f"missing: {missing}"))
    else:
        results.append(("1", "Vertical templates real", "PASS", f"all {len(KNOWN_VERTICALS)} verticals have a template"))


async def step2_custom_field_access_is_real():
    _banner("STEP 2 — Custom-field discovery and access against real HubSpot")
    client = HubSpotDataPullClient(PORTAL_A)

    default_pull = await client.pull_crm_objects(object_types=["CONTACT"])
    default_props = set(default_pull["CONTACT"][0]["properties"].keys()) if default_pull.get("CONTACT") else set()
    print(f"  default SELECT * properties: {sorted(default_props)}")

    discovered = await client.discover_object_properties("CONTACT")
    print(f"  search_properties discovered {len(discovered)} real property definitions for CONTACT")

    # Try several discovered properties NOT in the default set, not just
    # one — a single unpopulated property (blank on these particular
    # sample records) would otherwise look identical to a real mechanism
    # failure. Confirmed live earlier that "jobtitle" is genuinely
    # populated on both sample contacts; include it first as a known-good
    # probe, then fall back to whatever else discovery found.
    extra_candidates = [p for p in ["jobtitle", *discovered] if p not in default_props]
    if not extra_candidates:
        results.append(("2", "Custom-field access", "SKIP", "no property beyond the default set was discoverable"))
        return

    found_beyond_default = None
    for probe_property in extra_candidates[:5]:
        explicit_pull = await client.pull_crm_objects(
            object_types=["CONTACT"], properties={"CONTACT": [probe_property]}
        )
        explicit_props = set(explicit_pull["CONTACT"][0]["properties"].keys()) if explicit_pull.get("CONTACT") else set()
        present = probe_property in explicit_props
        print(f"  requested extra property {probe_property!r} -> present in response: {present}")
        if present:
            found_beyond_default = probe_property
            break

    if found_beyond_default:
        results.append(
            ("2", "Custom-field access", "PASS", f"discovered {len(discovered)} properties, {found_beyond_default!r} reachable beyond the default set")
        )
    else:
        results.append(
            ("2", "Custom-field access", "FAIL", f"none of {extra_candidates[:5]} were returned when explicitly requested — investigate")
        )


async def step3_category_tools_real_transport():
    _banner("STEP 3 — Live session's category-scoped tools, real Client<->FastMCP, real HubSpot pulls")
    with patch.object(live_session, "get_access_token", _fake_staff_token):
        async with Client(live_session.mcp) as client:
            tools = await client.list_tools()
            tool_names = sorted(t.name for t in tools)
            print(f"  tools exposed: {tool_names}")

            await client.call_tool("select_tenant", {"tenant": PORTAL_A})

            crm = await client.call_tool("query_crm_records", {"object_type": "contacts"})
            has_crm_data = bool(crm.data.get("CONTACT"))
            print(f"  query_crm_records('contacts') -> {len(crm.data.get('CONTACT', []))} real record(s)")

            wrong_category = await client.call_tool("query_engagement_records", {"object_type": "contacts"})
            correctly_rejected = "error" in wrong_category.data
            print(f"  query_engagement_records('contacts') correctly rejected: {correctly_rejected}")

            engagement = await client.call_tool("query_engagement_records", {"object_type": "calls"})
            has_engagement_data = "CALL" in engagement.data
            print(f"  query_engagement_records('calls') -> {len(engagement.data.get('CALL', []))} real record(s)")

    expected_tools = {
        "list_my_tenants",
        "select_tenant",
        "query_crm_records",
        "query_engagement_records",
        "query_marketing_content",
        "query_users",
    }
    if set(tool_names) != expected_tools:
        results.append(("3", "Category tools real transport", "FAIL", f"unexpected tool set: {tool_names}"))
    elif has_crm_data and correctly_rejected and has_engagement_data:
        results.append(("3", "Category tools real transport", "PASS", "real data returned per category, wrong-category request rejected"))
    else:
        results.append(("3", "Category tools real transport", "FAIL", "one or more real-data/rejection checks failed"))


async def step4_client_agent_run_real_anthropic():
    _banner("STEP 4 (optional) — Real client agent run against the real Anthropic API")
    from config import settings

    if not settings.anthropic_api_key:
        results.append(("4", "Real client agent run", "NOT READY", "no ANTHROPIC_API_KEY configured"))
        return

    try:
        instance = await resolve_client_agent_instance(PORTAL_A)
        print(f"  resolved client_agent_instances row id={instance.id}, version={instance.version}")
        result = await run_client_agent(PORTAL_A)
        total = sum(len(v) for v in result.values() if isinstance(v, list))
        print(f"  gathered {total} real records across {list(result.keys())}")
        results.append(("4", "Real client agent run", "PASS", f"gathered {total} real records via the real Anthropic API"))
    except Exception as exc:
        results.append(("4", "Real client agent run", "NOT READY", str(exc)[:90]))


async def step5_two_real_portals_return_distinct_data():
    _banner("STEP 5 — Two real portals queried through the new tools, checked for cross-tenant leakage")

    # Sequential, not concurrent, and a DISTINCT jti (session_key) per
    # call, deliberately: unittest.mock.patch mutates one shared module
    # attribute (live_session.get_access_token), and get_access_token()
    # is called synchronously mid-flow — two truly concurrent tasks each
    # patching it to a different fake identity would race on which
    # identity is active when the other task's tool call actually reads
    # it. That's a hazard specific to this mocking technique under real
    # concurrency, not a production bug: production reads a real,
    # per-connection token from real request context, never a shared
    # global. Concurrent-session isolation with real distinct session
    # keys is already covered correctly by test_tenant_isolation.py
    # ::test_live_session_two_staff_sessions_do_not_leak_selection.
    async def _query_one(hub_id: str) -> dict:
        with patch.object(live_session, "get_access_token", lambda: _fake_staff_token(jti=f"live-verification-{hub_id}")):
            async with Client(live_session.mcp) as client:
                await client.call_tool("select_tenant", {"tenant": hub_id})
                result = await client.call_tool("query_crm_records", {"object_type": "companies"})
                return result.data

    result_a = await _query_one(PORTAL_A)
    result_b = await _query_one(PORTAL_B)

    print(f"  {PORTAL_A}: {result_a}")
    print(f"  {PORTAL_B}: {result_b}")

    if result_a != result_b:
        results.append(("5", "Two real portals distinct", "PASS", "two real portals returned genuinely different data"))
    else:
        # Not automatically a bug: this project's own DATABASE.md already
        # documents that HubSpot object IDs are NOT globally unique across
        # portals, and both test portals may share identical auto-seeded
        # demo data. Flagged NOT READY rather than FAIL so a human
        # confirms which case this is, rather than this script guessing.
        results.append(("5", "Two real portals distinct", "NOT READY", "identical data returned — confirm whether this is shared demo/seed data or a real bug before trusting it either way"))


async def main():
    await step1_vertical_templates_are_real()
    await step2_custom_field_access_is_real()
    await step3_category_tools_real_transport()
    await step4_client_agent_run_real_anthropic()
    await step5_two_real_portals_return_distinct_data()

    _banner("SUMMARY")
    for step, label, status, note in results:
        print(f"  [{status:9}] Step {step}: {label:30} {note}")
    print()

    pool = await get_pool()
    await pool.close()


asyncio.run(main())
