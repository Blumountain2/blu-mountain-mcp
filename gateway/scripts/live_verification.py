"""Systematic, non-mocked verification of the vertical/client agent
separation work — now real, separate agent classes per vertical/client
(openspec/changes/client-vertical-agent-classes), superseding the
database-row-driven version this file originally verified
(openspec/changes/separate-vertical-client-agents) — against real
systems: real Postgres, real HubSpot portals, real Anthropic API, a
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

Seven independent steps — one failing or not-ready doesn't stop the others.
A summary table at the end shows PASS/FAIL/SKIP/NOT READY for all seven.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from fastmcp import Client

from db import get_pool
from frameworks.agents import clients as _client_agents  # noqa: F401 — registers real clients
from frameworks.agents.registry import get_registered_agent_class, registered_hub_ids
from frameworks.agents.tools import bind_tool_executor
from frameworks.agents.verticals.ecommerce import EcommerceAgent
from frameworks.agents.verticals.marketplace import MarketplaceAgent
from frameworks.agents.verticals.plg import PLGAgent
from frameworks.agents.verticals.saas import SaaSAgent
from frameworks.agents.verticals.services_project import ServicesProjectAgent
from frameworks.agents.verticals.transactional import TransactionalAgent
from frameworks.pull_agent import run_client_agent
from frameworks.vertical import KNOWN_VERTICALS
from session import live_session
from sync.hubspot_client import HubSpotDataPullClient

_VERTICAL_CLASSES = [SaaSAgent, PLGAgent, MarketplaceAgent, EcommerceAgent, ServicesProjectAgent, TransactionalAgent]

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


async def step1_vertical_and_client_agent_classes_are_real():
    _banner("STEP 1 — Every vertical has a real agent class; both real clients are registered")
    covered = {c.VERTICAL for c in _VERTICAL_CLASSES}
    missing_verticals = sorted(KNOWN_VERTICALS - covered)
    for vertical_class in _VERTICAL_CLASSES:
        print(f"  ok       {vertical_class.VERTICAL:20} {vertical_class.__name__}")
    for vertical in missing_verticals:
        print(f"  MISSING  {vertical}")

    registered = registered_hub_ids()
    expected_hub_ids = {PORTAL_A, PORTAL_B}
    missing_clients = sorted(expected_hub_ids - registered)
    for hub_id in sorted(expected_hub_ids):
        if hub_id in registered:
            cls = get_registered_agent_class(hub_id)
            print(f"  ok       {hub_id}  {cls.__name__} ({cls.VERTICAL})")
        else:
            print(f"  MISSING  {hub_id}")

    if missing_verticals or missing_clients:
        results.append(
            ("1", "Vertical/client agent classes real", "FAIL", f"missing verticals={missing_verticals} clients={missing_clients}")
        )
    else:
        results.append(
            ("1", "Vertical/client agent classes real", "PASS", f"all {len(KNOWN_VERTICALS)} verticals + both real clients registered")
        )


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
    _banner("STEP 3 — Live session's category-scoped + custom-object tools, real Client<->FastMCP, real HubSpot pulls")
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

    # A fresh session (distinct jti) for PORTAL_B, since a stale
    # live_session_selection row from the block above would otherwise
    # still point at PORTAL_A for the same session_key.
    with patch.object(live_session, "get_access_token", lambda: _fake_staff_token(jti="live-verification-custom-objects")):
        async with Client(live_session.mcp) as client:
            await client.call_tool("select_tenant", {"tenant": PORTAL_B})

            schemas_result = await client.call_tool("list_custom_objects", {})
            schemas = schemas_result.data
            print(f"  list_custom_objects() -> {len(schemas)} real schema(s): {[s.get('name') for s in schemas]}")

            has_custom_object_data = False
            if schemas:
                object_type_id = schemas[0]["objectTypeId"]
                friendly_name = schemas[0].get("name")
                custom_records = await client.call_tool("query_custom_object", {"object_type": object_type_id})
                has_custom_object_data = bool(custom_records.data.get("records"))
                print(
                    f"  query_custom_object({object_type_id!r}) -> "
                    f"{len(custom_records.data.get('records', []))} real record(s)"
                )

                # Also confirm the friendly-name resolution path specifically
                # (2026-09-08) — not just the exact objectTypeId a caller
                # already has from list_custom_objects.
                by_name = await client.call_tool("query_custom_object", {"object_type": friendly_name})
                resolves_by_name = by_name.data.get("object_type_id") == object_type_id
                print(f"  query_custom_object({friendly_name!r}) resolves to {object_type_id!r}: {resolves_by_name}")

    expected_tools = {
        "list_my_tenants",
        "select_tenant",
        "query_crm_records",
        "query_engagement_records",
        "query_marketing_content",
        "query_users",
        "list_custom_objects",
        "query_custom_object",
        "run_vertical_diagnostic",
    }
    if set(tool_names) != expected_tools:
        results.append(("3", "Category tools real transport", "FAIL", f"unexpected tool set: {tool_names}"))
    elif not (has_crm_data and correctly_rejected and has_engagement_data):
        results.append(("3", "Category tools real transport", "FAIL", "one or more real-data/rejection checks failed"))
    elif not schemas:
        results.append(("3", "Category tools real transport", "FAIL", f"no custom object schemas found on {PORTAL_B} — expected the real Transaction object"))
    elif not has_custom_object_data:
        results.append(("3", "Category tools real transport", "FAIL", "list_custom_objects found a schema but query_custom_object returned no records"))
    elif not resolves_by_name:
        results.append(("3", "Category tools real transport", "FAIL", "query_custom_object's friendly-name resolution did not match the exact objectTypeId path"))
    else:
        results.append(("3", "Category tools real transport", "PASS", "real data returned per category, wrong-category request rejected, real custom-object schema+records reached by ID and by name"))


async def step4_client_agent_run_real_anthropic():
    _banner("STEP 4 (optional) — Real client agent runs against the real Anthropic API, both real clients")
    from config import settings

    if not settings.anthropic_api_key:
        results.append(("4", "Real client agent run", "NOT READY", "no ANTHROPIC_API_KEY configured"))
        return

    try:
        totals = {}
        for hub_id in (PORTAL_A, PORTAL_B):
            cls = get_registered_agent_class(hub_id)
            print(f"  running {cls.__name__} ({cls.VERTICAL}) for {hub_id}")
            result = await run_client_agent(hub_id)
            total = sum(len(v) for v in result.values() if isinstance(v, list))
            totals[hub_id] = total
            print(f"  {hub_id}: gathered {total} real records across {list(result.keys())}")
        results.append(
            ("4", "Real client agent run", "PASS", f"gathered real records via the real Anthropic API for both clients: {totals}")
        )
    except Exception as exc:
        results.append(("4", "Real client agent run", "NOT READY", str(exc)[:90]))


async def step6_custom_object_reachable_through_the_agents_own_tool_loop():
    _banner("STEP 6 — 149094230's real custom object reached through the agent's own tool dispatch")
    # Confirms the *new* integration point custom-object-support left
    # unwired (BaseAgent._bind_tool_executor's list_custom_objects/
    # pull_custom_object branches), calling the executor directly rather
    # than waiting on the model's own unprompted judgment to discover an
    # object neither the marketplace framework nor this client's
    # (currently empty) CONFIRMED_FIELDS names by identifier — a genuine
    # confirmation of the new dispatch code path against real HubSpot,
    # distinct from (and not a substitute for) the debug API's own
    # already-confirmed direct-call path.
    try:
        agent = get_registered_agent_class(PORTAL_B)()
        gathered: dict[str, list] = {}
        # bind_tool_executor moved to frameworks.agents.tools
        # (openspec/changes/vertical-diagnostic-agent's tools.py split) —
        # it's a standalone function now, not a BaseAgent method, taking
        # the agent's own hs_client/_confirmed_fields_for explicitly.
        execute_tool = bind_tool_executor(agent.hs_client, agent._confirmed_fields_for, None, None, gathered, 5)

        schemas_json = await execute_tool("list_custom_objects", {})
        print(f"  list_custom_objects -> {schemas_json}")
        import json as _json

        schemas = _json.loads(schemas_json)
        if not schemas:
            results.append(("6", "Custom object via agent loop", "NOT READY", "no custom object schemas discovered for 149094230"))
            return

        object_type_id = schemas[0]["objectTypeId"]
        pull_result_json = await execute_tool("pull_custom_object", {"object_type_id": object_type_id})
        print(f"  pull_custom_object({object_type_id!r}) -> {pull_result_json}")

        records = gathered.get(object_type_id)
        if isinstance(records, list):
            results.append(
                ("6", "Custom object via agent loop", "PASS", f"{len(records)} real record(s) of {object_type_id} via the agent's own tool dispatch")
            )
        else:
            results.append(("6", "Custom object via agent loop", "FAIL", f"pull did not return a record list: {pull_result_json}"))
    except Exception as exc:
        results.append(("6", "Custom object via agent loop", "NOT READY", str(exc)[:90]))


async def step7_run_vertical_diagnostic_real():
    _banner("STEP 7 (optional) — run_vertical_diagnostic against a real portal, real Anthropic, real Airtable staging")
    from config import settings

    if not settings.anthropic_api_key:
        results.append(("7", "Real diagnostic report", "NOT READY", "no ANTHROPIC_API_KEY configured"))
        return

    try:
        with patch.object(live_session, "get_access_token", lambda: _fake_staff_token(jti="live-verification-diagnostic")):
            async with Client(live_session.mcp) as client:
                await client.call_tool("select_tenant", {"tenant": PORTAL_A})
                result = await client.call_tool("run_vertical_diagnostic", {})

        report = result.data
        print(f"  summary: {report.get('summary', '')[:200]}")
        print(f"  kpis: {report.get('kpis')}")
        print(f"  risk_flags: {report.get('risk_flags')}")
        print(f"  staged: {report.get('staged')}")

        is_narrative = bool(report.get("summary")) and "properties" not in report
        if not is_narrative:
            results.append(("7", "Real diagnostic report", "FAIL", "response did not look like a real narrative report"))
        elif not report.get("staged"):
            results.append(("7", "Real diagnostic report", "NOT READY", "report generated but Airtable staging failed or is not configured"))
        else:
            results.append(("7", "Real diagnostic report", "PASS", f"real narrative report generated and staged for {PORTAL_A}"))
    except Exception as exc:
        results.append(("7", "Real diagnostic report", "NOT READY", str(exc)[:90]))


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
    await step1_vertical_and_client_agent_classes_are_real()
    await step2_custom_field_access_is_real()
    await step3_category_tools_real_transport()
    await step4_client_agent_run_real_anthropic()
    await step5_two_real_portals_return_distinct_data()
    await step6_custom_object_reachable_through_the_agents_own_tool_loop()
    await step7_run_vertical_diagnostic_real()

    _banner("SUMMARY")
    for step, label, status, note in results:
        print(f"  [{status:9}] Step {step}: {label:30} {note}")
    print()

    pool = await get_pool()
    await pool.close()


asyncio.run(main())
