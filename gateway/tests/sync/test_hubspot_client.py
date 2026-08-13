"""Task 3.6: proves a per-tenant HubSpot pull produces a complete read-only
snapshot with no cross-tenant token or data leakage, and that write-shaped
tools are never called. Uses a fake MCP client, no real HubSpot connection."""

import json
from types import SimpleNamespace

import pytest

from sync import hubspot_client
from sync.hubspot_client import HubSpotDataPullClient, ReadOnlyViolation


class _FakeTool:
    def __init__(self, name):
        self.name = name


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeMCPClient:
    def __init__(self, tools, responses):
        self._tools = [_FakeTool(name) for name in tools]
        self._responses = responses
        self.called_with_token = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def list_tools(self):
        return self._tools

    async def call_tool(self, name, params):
        return _FakeResult(self._responses.get(name, {"id": f"{name}-1"}))


def _patch_client(monkeypatch, tools, responses, token_log):
    async def fake_client(self, access_token):
        token_log.setdefault(self.hub_id, []).append(access_token)
        return _FakeMCPClient(tools, responses)

    monkeypatch.setattr(HubSpotDataPullClient, "_client", fake_client)

    async def fake_get_access_token(hub_id):
        return f"access-token-for-{hub_id}"

    monkeypatch.setattr(hubspot_client.mcp_vault, "get_access_token", fake_get_access_token)


@pytest.mark.asyncio
async def test_list_read_only_tools_excludes_write_tools_and_out_of_scope(monkeypatch):
    tools = [
        "list_contacts",
        "create_contact",
        "search_deals",
        "update_deal",
        "delete_ticket",
        "unrelated_widget_tool",
    ]
    _patch_client(monkeypatch, tools, {}, {})

    client = HubSpotDataPullClient("hub_a")
    selected = await client.list_read_only_tools()

    assert "list_contacts" in selected
    assert "search_deals" in selected
    assert "create_contact" not in selected
    assert "update_deal" not in selected
    assert "delete_ticket" not in selected
    assert "unrelated_widget_tool" not in selected


def test_is_read_safe_rejects_unrecognized_name_with_no_read_verb():
    """The actual scenario this guard exists for: a mutating action whose
    name contains no word in _WRITE_VERBS and no recognized read verb
    either. A blocklist-only check would have called this "safe" purely
    because nothing matched; the read-verb allowlist must reject it
    instead, since this module's token carries no OAuth scope of its own
    to fall back on."""
    assert hubspot_client._is_read_safe("notify_owner") is False
    assert hubspot_client._is_read_safe("flag_deal") is False
    assert hubspot_client._is_read_safe("ping_ticket") is False


def test_is_read_safe_rejects_write_verb_even_with_a_recognized_write_word():
    # close/resolve/assign are themselves in the broadened _WRITE_VERBS —
    # caught by the write-verb check directly, not just by lacking a read
    # verb (see test_is_read_safe_rejects_unrecognized_name_with_no_read_verb
    # for that separate, no-verb-at-all case).
    assert hubspot_client._is_read_safe("close_ticket") is False
    assert hubspot_client._is_read_safe("resolve_ticket") is False
    assert hubspot_client._is_read_safe("assign_deal") is False


def test_is_read_safe_rejects_compound_name_with_read_and_write_verb():
    # The gap a bare "has a read verb, has no write verb" check would
    # miss: a name that has BOTH. A tool like this would otherwise pass
    # _has_write_verb (no listed write verb) purely because the read verb
    # happens to come first in the name.
    assert hubspot_client._is_read_safe("get_and_send_email") is False
    assert hubspot_client._is_read_safe("search_and_enroll_contacts") is False


def test_is_read_safe_accepts_recognized_read_verbs():
    assert hubspot_client._is_read_safe("list_contacts") is True
    assert hubspot_client._is_read_safe("get_deal") is True
    assert hubspot_client._is_read_safe("search_tickets") is True


@pytest.mark.asyncio
async def test_list_read_only_tools_excludes_unrecognized_names_even_without_write_verb(monkeypatch):
    """Distinct from the write-tools case: a name with neither a write verb
    nor a read verb must still be excluded, not defaulted to safe."""
    tools = ["list_contacts", "close_ticket"]
    _patch_client(monkeypatch, tools, {}, {})

    client = HubSpotDataPullClient("hub_a")
    selected = await client.list_read_only_tools()

    assert "list_contacts" in selected
    assert "close_ticket" not in selected


@pytest.mark.asyncio
async def test_pull_object_refuses_write_shaped_tool(monkeypatch):
    _patch_client(monkeypatch, ["create_contact"], {}, {})
    client = HubSpotDataPullClient("hub_a")

    with pytest.raises(ReadOnlyViolation):
        await client.pull_object("create_contact")


@pytest.mark.asyncio
async def test_pull_object_refuses_unrecognized_tool_with_no_read_verb(monkeypatch):
    """Same guard, the actual tickets-scope scenario: a name with no
    recognized write verb either must still be refused, not called on the
    assumption that "not obviously a write" means "safe to call"."""
    _patch_client(monkeypatch, ["close_ticket"], {}, {})
    client = HubSpotDataPullClient("hub_a")

    with pytest.raises(ReadOnlyViolation):
        await client.pull_object("close_ticket")


@pytest.mark.asyncio
async def test_pull_all_produces_snapshot_of_in_scope_objects(monkeypatch):
    tools = ["list_contacts", "list_deals"]
    responses = {
        "list_contacts": {"id": "contact-1", "email": "a@example.com"},
        "list_deals": {"id": "deal-1", "amount": 100},
    }
    _patch_client(monkeypatch, tools, responses, {})

    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_all()

    assert result["list_contacts"] == {"id": "contact-1", "email": "a@example.com"}
    assert result["list_deals"] == {"id": "deal-1", "amount": 100}


@pytest.mark.asyncio
async def test_pull_uses_only_this_tenants_token_never_anothers(monkeypatch):
    token_log: dict[str, list[str]] = {}
    _patch_client(monkeypatch, ["list_contacts"], {"list_contacts": {"id": "c-1"}}, token_log)

    client_a = HubSpotDataPullClient("hub_a")
    client_b = HubSpotDataPullClient("hub_b")

    await client_a.pull_all()
    await client_b.pull_all()

    # pull_all() now opens exactly one connection (and fetches the access
    # token exactly once) for the whole pull — reused across tool
    # discovery, every generic tool, every CRM_OBJECT_TYPES entry, and
    # campaign enumeration — instead of one connection per tool/object
    # call. What matters for isolation is that the one connection made for
    # hub_a used only hub_a's token, and likewise for hub_b.
    assert token_log["hub_a"] == ["access-token-for-hub_a"]
    assert token_log["hub_b"] == ["access-token-for-hub_b"]
    # Neither tenant's pull ever saw the other tenant's token.
    assert "access-token-for-hub_b" not in token_log["hub_a"]
    assert "access-token-for-hub_a" not in token_log["hub_b"]


@pytest.mark.asyncio
async def test_pull_failure_for_one_tool_does_not_leak_into_others(monkeypatch):
    class _FailingMCPClient(_FakeMCPClient):
        async def call_tool(self, name, params):
            if name == "list_contacts":
                raise RuntimeError("simulated upstream failure")
            return await super().call_tool(name, params)

    async def fake_client(self, access_token):
        return _FailingMCPClient(["list_contacts", "list_deals"], {"list_deals": {"id": "deal-1"}})

    monkeypatch.setattr(HubSpotDataPullClient, "_client", fake_client)

    async def fake_get_access_token(hub_id):
        return "token"

    monkeypatch.setattr(hubspot_client.mcp_vault, "get_access_token", fake_get_access_token)

    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_all()

    assert result["list_contacts"] == {"error": "pull_failed"}
    assert result["list_deals"] == {"id": "deal-1"}


@pytest.mark.asyncio
async def test_pull_all_degrades_gracefully_when_mcp_auth_not_installed(monkeypatch):
    """A tenant that completed only the Public App install has no mcp_tokens
    row yet (a valid, documented interim state — see
    context/ONBOARDING_RUNBOOK.md). get_access_token raises HTTPException
    404 for it; pull_all() must catch that itself and log it as a
    hubspot_pull.tool_failed event (the same event name every other
    per-tool failure uses, and the one operators are told to check), not
    let it propagate uncaught into the scheduled job's generic
    cycle-level failure handler."""
    from fastapi import HTTPException

    async def fake_get_access_token(hub_id):
        raise HTTPException(404, "Unknown tenant")

    monkeypatch.setattr(hubspot_client.mcp_vault, "get_access_token", fake_get_access_token)

    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_all()

    assert result == {"error": "pull_failed"}


# query_crm_data: the confirmed-real, only-real-way to read the core CRM
# object set (contacts, companies, deals, tickets, etc.) — see this
# module's docstring for why it can't go through the name-based filter
# above, and why _is_safe_select exists as defense in depth even though
# pull_crm_objects() only ever authors the SQL itself.


def test_is_safe_select_accepts_plain_select():
    assert hubspot_client._is_safe_select("SELECT * FROM CONTACT") is True
    assert hubspot_client._is_safe_select("select * from deal;") is True
    assert hubspot_client._is_safe_select(
        "SELECT hubspot_owner_id, SUM(amount_in_home_currency) FROM DEAL GROUP BY hubspot_owner_id"
    ) is True


def test_is_safe_select_rejects_non_select_statements():
    assert hubspot_client._is_safe_select("UPDATE contact SET firstname = 'x'") is False
    assert hubspot_client._is_safe_select("INSERT INTO contact (firstname) VALUES ('x')") is False
    assert hubspot_client._is_safe_select("DELETE FROM deal") is False
    assert hubspot_client._is_safe_select("DROP TABLE contact") is False


def test_is_safe_select_rejects_stacked_statements():
    """The actual injection shape this guard exists for: a query that
    starts with a plain SELECT (passing a naive prefix check) but smuggles
    a mutating statement after a semicolon."""
    assert hubspot_client._is_safe_select("SELECT * FROM CONTACT; DROP TABLE contact") is False
    assert hubspot_client._is_safe_select("SELECT * FROM CONTACT; DELETE FROM contact;") is False


def test_is_safe_select_rejects_write_keyword_anywhere_in_statement():
    # Not just a prefix check: a write-shaped clause later in an otherwise
    # SELECT-prefixed statement must still be refused.
    assert hubspot_client._is_safe_select("SELECT * FROM CONTACT WHERE update = 'x'") is False


def test_is_safe_select_accepts_bare_set_and_into_as_ordinary_words():
    # "set"/"into" are only meaningful as part of UPDATE...SET / INSERT
    # INTO, and those parent keywords are already blocked above — a bare
    # occurrence (a property name, an alias, a literal) must not
    # false-positive-reject an otherwise-safe SELECT.
    assert hubspot_client._is_safe_select(
        "SELECT job_offer_set FROM CONTACT WHERE description = 'a mind set'"
    ) is True
    assert hubspot_client._is_safe_select(
        "SELECT sales_into_the_future FROM DEAL"
    ) is True


@pytest.mark.asyncio
async def test_pull_object_refuses_query_crm_data_with_non_select_sql(monkeypatch):
    _patch_client(monkeypatch, ["query_crm_data"], {}, {})
    client = HubSpotDataPullClient("hub_a")

    with pytest.raises(ReadOnlyViolation):
        await client.pull_object("query_crm_data", sql="DELETE FROM contact")


@pytest.mark.asyncio
async def test_pull_object_allows_query_crm_data_with_plain_select(monkeypatch):
    _patch_client(
        monkeypatch,
        ["query_crm_data"],
        {"query_crm_data": {"id": "contact-1"}},
        {},
    )
    client = HubSpotDataPullClient("hub_a")

    result = await client.pull_object("query_crm_data", sql="SELECT * FROM CONTACT")

    assert result == {"id": "contact-1"}


# _extract_result / _unwrap_query_crm_data: regression tests locking in
# the exact real response shapes confirmed live against mcp.hubspot.com.
# None of HubSpot's real tools declare an outputSchema, so FastMCP's
# result.data/.structured_content are always None in production — the
# real payload is JSON text inside result.content[0].text instead. The
# _FakeMCPClient/_FakeResult used elsewhere in this file set .data
# directly and so never exercise this fallback path; these tests use a
# bare object shaped like the real CallToolResult instead.


def _content_result(text):
    return SimpleNamespace(data=None, structured_content=None, content=[SimpleNamespace(text=text)])


def test_extract_result_falls_back_to_content_when_data_is_none():
    # Confirmed live: search_owners' real response.
    real_payload = {"owners": [{"ownerId": 1, "name": "A", "isActive": True}], "hasMore": False}
    result = _content_result(json.dumps(real_payload))

    assert hubspot_client._extract_result(result) == real_payload


def test_extract_result_prefers_data_when_present():
    result = SimpleNamespace(data={"already": "structured"}, content=None)
    assert hubspot_client._extract_result(result) == {"already": "structured"}


def test_unwrap_query_crm_data_flattens_citation_envelope():
    # Confirmed live: query_crm_data's real response for "SELECT * FROM
    # CONTACT" against the test portal — each record is double-encoded
    # (a JSON string inside the "content" field of each "results" entry),
    # with a non-data "instructions" field mixed in alongside it.
    envelope = {
        "results": [
            {"content": json.dumps({"objectTypeId": "0-1", "properties": {"firstname": "Brian"}})},
            {"content": json.dumps({"objectTypeId": "0-1", "properties": {"firstname": "Maria"}})},
        ],
        "instructions": "If response contains citations...",
    }

    records = hubspot_client._unwrap_query_crm_data(envelope)

    assert records == [
        {"objectTypeId": "0-1", "properties": {"firstname": "Brian"}},
        {"objectTypeId": "0-1", "properties": {"firstname": "Maria"}},
    ]


def test_unwrap_query_crm_data_leaves_non_envelope_values_unchanged():
    # Guards against ever assuming every tool response looks like
    # query_crm_data's envelope — this is only applied when tool_name is
    # in _SQL_QUERY_TOOLS, and even then should no-op on an unexpected shape
    # rather than raise or silently drop data.
    assert hubspot_client._unwrap_query_crm_data({"owners": []}) == {"owners": []}
    assert hubspot_client._unwrap_query_crm_data(None) is None


@pytest.mark.asyncio
async def test_pull_crm_objects_queries_every_confirmed_object_type(monkeypatch):
    seen_sql: list[str] = []

    class _RecordingMCPClient(_FakeMCPClient):
        async def call_tool(self, name, params):
            seen_sql.append(params["sql"])
            return await super().call_tool(name, params)

    async def fake_client(self, access_token):
        return _RecordingMCPClient(["query_crm_data"], {})

    monkeypatch.setattr(HubSpotDataPullClient, "_client", fake_client)

    async def fake_get_access_token(hub_id):
        return "token"

    monkeypatch.setattr(hubspot_client.mcp_vault, "get_access_token", fake_get_access_token)

    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_crm_objects()

    assert set(result.keys()) == set(hubspot_client.CRM_OBJECT_TYPES)
    for object_type in hubspot_client.CRM_OBJECT_TYPES:
        assert f"SELECT * FROM {object_type}" in seen_sql


def test_crm_object_types_covers_segments_landing_pages_and_blog_posts():
    # Confirmed live via query_crm_data against the real endpoint: these
    # three are plain queryable object types, the same mechanism as every
    # other entry, resolving what were earlier thought to be gaps (spec's
    # "segments"/"landing pages"/"blog posts" reference objects).
    assert "OBJECT_LIST" in hubspot_client.CRM_OBJECT_TYPES
    assert "LANDING_PAGE" in hubspot_client.CRM_OBJECT_TYPES
    assert "BLOG_POST" in hubspot_client.CRM_OBJECT_TYPES


def test_crm_object_aliases_cover_every_object_type():
    # A new CRM_OBJECT_TYPES entry with no matching CRM_OBJECT_ALIASES
    # entry would silently never match any free-text query in
    # session/live_session.py's query_hubspot_data — the same class of
    # silent-drop bug that made "companies"/"meetings" unmatchable before
    # this alias table existed. Caught here at test time, not discovered
    # by a staff member getting an empty result with no error.
    assert set(hubspot_client.CRM_OBJECT_ALIASES.keys()) == set(hubspot_client.CRM_OBJECT_TYPES)
    for object_type, aliases in hubspot_client.CRM_OBJECT_ALIASES.items():
        assert aliases, f"{object_type} has no query aliases"


def test_crm_object_aliases_match_common_irregular_plurals():
    # The specific failure this alias table exists to fix: naive substring
    # matching against the bare type name misses these.
    assert "companies" in hubspot_client.CRM_OBJECT_ALIASES["COMPANY"]
    assert "meetings" in hubspot_client.CRM_OBJECT_ALIASES["MEETING_EVENT"]
    assert "landing pages" in hubspot_client.CRM_OBJECT_ALIASES["LANDING_PAGE"]
    assert "blog posts" in hubspot_client.CRM_OBJECT_ALIASES["BLOG_POST"]


# list_read_only_tools()'s out-of-scope branch: a tool can be read-safe
# (matches a read verb, no write verb) but not match any in-scope object
# keyword. This used to be silently dropped with no logging at all — which
# is exactly how get_organization_details (the real path to the spec's
# "teams" object) went unnoticed. Now it's a distinct, logged bucket.


def test_is_in_scope_matches_organization_for_get_organization_details():
    assert hubspot_client._is_in_scope("get_organization_details") is True


@pytest.mark.asyncio
async def test_list_read_only_tools_includes_get_organization_details(monkeypatch):
    tools = ["get_organization_details", "search_conversations"]
    _patch_client(monkeypatch, tools, {}, {})

    client = HubSpotDataPullClient("hub_a")
    selected = await client.list_read_only_tools()

    assert "get_organization_details" in selected
    # Read-safe (matches "search") but not in scope (no spec object
    # keyword matches) — excluded, but via the dedicated out-of-scope
    # bucket, not silently.
    assert "search_conversations" not in selected


# _DEFAULT_TOOL_PARAMS: get_content_analytics_report and
# get_marketing_email_analytics both have a genuinely required field their
# schema rejects an empty call without, confirmed live with real HubSpot
# responses (not "Not Authorized"/schema-validation errors). pull_all()
# supplies these automatically; get_campaign_attribution_reports and
# read_campaign_data are deliberately NOT here (see the module's own
# comment on _DEFAULT_TOOL_PARAMS for why).


@pytest.mark.asyncio
async def test_pull_all_supplies_default_params_for_content_analytics(monkeypatch):
    seen_params = {}

    class _RecordingMCPClient(_FakeMCPClient):
        async def call_tool(self, name, params):
            seen_params[name] = params
            return await super().call_tool(name, params)

    async def fake_client(self, access_token):
        return _RecordingMCPClient(["get_content_analytics_report"], {})

    monkeypatch.setattr(HubSpotDataPullClient, "_client", fake_client)

    async def fake_get_access_token(hub_id):
        return "token"

    monkeypatch.setattr(hubspot_client.mcp_vault, "get_access_token", fake_get_access_token)

    client = HubSpotDataPullClient("hub_a")
    await client.pull_all()

    assert seen_params["get_content_analytics_report"] == {"mode": "TOTALS"}


@pytest.mark.asyncio
async def test_pull_all_supplies_default_params_for_marketing_email_analytics(monkeypatch):
    seen_params = {}

    class _RecordingMCPClient(_FakeMCPClient):
        async def call_tool(self, name, params):
            seen_params[name] = params
            return await super().call_tool(name, params)

    async def fake_client(self, access_token):
        return _RecordingMCPClient(["get_marketing_email_analytics"], {})

    monkeypatch.setattr(HubSpotDataPullClient, "_client", fake_client)

    async def fake_get_access_token(hub_id):
        return "token"

    monkeypatch.setattr(hubspot_client.mcp_vault, "get_access_token", fake_get_access_token)

    client = HubSpotDataPullClient("hub_a")
    await client.pull_all()

    mode = seen_params["get_marketing_email_analytics"]["mode"]
    assert mode["_type"] == "OVERVIEW"
    assert "startDate" in mode["statisticsSection"]
    assert "endDate" in mode["statisticsSection"]


@pytest.mark.asyncio
async def test_pull_all_passes_no_default_params_for_unlisted_tools(monkeypatch):
    seen_params = {}

    class _RecordingMCPClient(_FakeMCPClient):
        async def call_tool(self, name, params):
            seen_params[name] = params
            return await super().call_tool(name, params)

    async def fake_client(self, access_token):
        return _RecordingMCPClient(["search_owners"], {})

    monkeypatch.setattr(HubSpotDataPullClient, "_client", fake_client)

    async def fake_get_access_token(hub_id):
        return "token"

    monkeypatch.setattr(hubspot_client.mcp_vault, "get_access_token", fake_get_access_token)

    client = HubSpotDataPullClient("hub_a")
    await client.pull_all()

    assert seen_params["search_owners"] == {}


# get_campaign_attribution_reports / read_campaign_data: confirmed live
# against a real Enterprise-tier test account with a real campaign (see
# design.md's decision log) — both work once called correctly, unlike the
# earlier "Not Authorized"/account-tier-gated finding on a test account
# without Campaigns enabled.


def test_crm_object_types_covers_campaign():
    assert "CAMPAIGN" in hubspot_client.CRM_OBJECT_TYPES


@pytest.mark.asyncio
async def test_pull_all_supplies_default_params_for_campaign_attribution_reports(monkeypatch):
    seen_params = {}

    class _RecordingMCPClient(_FakeMCPClient):
        async def call_tool(self, name, params):
            seen_params[name] = params
            return await super().call_tool(name, params)

    async def fake_client(self, access_token):
        return _RecordingMCPClient(["get_campaign_attribution_reports"], {})

    monkeypatch.setattr(HubSpotDataPullClient, "_client", fake_client)

    async def fake_get_access_token(hub_id):
        return "token"

    monkeypatch.setattr(hubspot_client.mcp_vault, "get_access_token", fake_get_access_token)

    client = HubSpotDataPullClient("hub_a")
    await client.pull_all()

    params = seen_params["get_campaign_attribution_reports"]
    assert params["metrics"] == ["REVENUE", "DEAL_COUNT"]
    assert params["hasReadToolInstructions"] is True


@pytest.mark.asyncio
async def test_pull_all_never_calls_read_campaign_data_with_no_params(monkeypatch):
    """read_campaign_data's name passes the generic read-verb/in-scope
    filter (matches "read" + "campaign"), so without the _PER_ITEM_TOOLS
    exclusion it would be called bare by the generic loop and always fail
    — every operation requires a real campaignCrmObjectId."""
    seen_params = {}

    class _RecordingMCPClient(_FakeMCPClient):
        async def call_tool(self, name, params):
            seen_params.setdefault(name, []).append(params)
            return await super().call_tool(name, params)

    async def fake_client(self, access_token):
        return _RecordingMCPClient(["read_campaign_data"], {})

    monkeypatch.setattr(HubSpotDataPullClient, "_client", fake_client)

    async def fake_get_access_token(hub_id):
        return "token"

    monkeypatch.setattr(hubspot_client.mcp_vault, "get_access_token", fake_get_access_token)

    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_all()

    assert "read_campaign_data" not in seen_params
    assert "read_campaign_data" not in result


@pytest.mark.asyncio
async def test_pull_campaign_data_enumerates_and_queries_each_campaign(monkeypatch):
    seen_read_campaign_calls = []

    class _RecordingMCPClient(_FakeMCPClient):
        async def call_tool(self, name, params):
            if name == "query_crm_data":
                return _FakeResult(
                    {
                        "results": [
                            {"content": json.dumps({"properties": {"hs_object_id": "111"}})},
                            {"content": json.dumps({"properties": {"hs_object_id": "222"}})},
                        ]
                    }
                )
            if name == "read_campaign_data":
                seen_read_campaign_calls.append(params)
                return _FakeResult({"analyticsResponse": {"responses": []}})
            return await super().call_tool(name, params)

    async def fake_client(self, access_token):
        return _RecordingMCPClient(["query_crm_data", "read_campaign_data"], {})

    monkeypatch.setattr(HubSpotDataPullClient, "_client", fake_client)

    async def fake_get_access_token(hub_id):
        return "token"

    monkeypatch.setattr(hubspot_client.mcp_vault, "get_access_token", fake_get_access_token)

    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_campaign_data()

    # A list of per-campaign records, each carrying its own "id" — the
    # same shape every other object type is staged in, not a dict keyed by
    # campaign ID (see airtable_staging.stage_tenant_pull).
    assert {record["id"] for record in result} == {"111", "222"}
    called_ids = {
        c["analyticsRequest"]["requests"][0]["campaignCrmObjectId"] for c in seen_read_campaign_calls
    }
    assert called_ids == {111, 222}
    for call in seen_read_campaign_calls:
        assert call["operation"] == "GET_ANALYTICS"
        assert call["analyticsRequest"]["requests"][0]["requestedData"] == "METRICS"


@pytest.mark.asyncio
async def test_pull_campaign_data_returns_empty_when_campaign_query_fails(monkeypatch):
    class _FailingMCPClient(_FakeMCPClient):
        async def call_tool(self, name, params):
            if name == "query_crm_data":
                raise RuntimeError("simulated CAMPAIGN access failure")
            return await super().call_tool(name, params)

    async def fake_client(self, access_token):
        return _FailingMCPClient(["query_crm_data"], {})

    monkeypatch.setattr(HubSpotDataPullClient, "_client", fake_client)

    async def fake_get_access_token(hub_id):
        return "token"

    monkeypatch.setattr(hubspot_client.mcp_vault, "get_access_token", fake_get_access_token)

    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_campaign_data()

    assert result == []
