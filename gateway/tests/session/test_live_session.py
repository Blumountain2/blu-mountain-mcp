"""Unit tests for session/live_session.py's staff-identity extraction and
query_hubspot_data's routing across sync/hubspot_client.py's three read
paths. conftest.py's autouse _pool fixture opens a real Postgres connection
for every test in this suite — there's no DB-independent test tier here."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from db import get_pool
from session import live_session
from sync import hubspot_client
from sync.hubspot_client import HubSpotDataPullClient


def _fake_token(email: str, hd: str = "blumountain.me", jti: str = "jti-1"):
    return SimpleNamespace(claims={"email": email, "hd": hd, "jti": jti}, token="raw-token")


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

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def list_tools(self):
        return self._tools

    async def call_tool(self, name, params):
        if name == "query_crm_data":
            return _FakeResult(self._responses.get("query_crm_data", {"results": []}))
        return _FakeResult(self._responses.get(name, {"id": f"{name}-1"}))


async def _seed_single_tenant(hub_id: str, monkeypatch, tools, responses):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'installed')", hub_id
    )

    async def fake_client(self, access_token):
        return _FakeMCPClient(tools, responses)

    monkeypatch.setattr(HubSpotDataPullClient, "_client", fake_client)

    async def fake_get_access_token(hub_id):
        return "access-token"

    monkeypatch.setattr(hubspot_client.mcp_vault, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(
        live_session, "get_access_token", lambda: _fake_token("staff@blumountain.me")
    )
    monkeypatch.setattr(live_session, "record_audit", AsyncMock())


@pytest.mark.asyncio
async def test_require_staff_identity_lowercases_email(monkeypatch):
    """staff_identity must be normalized once, here, since it's compared
    against staff_tenant_restrictions rows that may have been hand-typed
    with different casing — a mismatch should never silently fail open."""
    monkeypatch.setattr(live_session, "get_access_token", lambda: _fake_token("Person@BluMountain.me"))

    email, _session_key = await live_session._require_staff_identity()

    assert email == "person@blumountain.me"


@pytest.mark.asyncio
async def test_require_staff_identity_accepts_domain_regardless_of_casing(monkeypatch):
    """The allowlist comparison must be as casing-tolerant as the email
    comparison — a legitimate staff member must never be rejected just
    because Google's hd claim and FASTMCP_ALLOWED_GOOGLE_DOMAINS disagree
    on casing for the same real-world domain."""
    monkeypatch.setattr(
        live_session, "get_access_token", lambda: _fake_token("person@blumountain.me", hd="BluMountain.ME")
    )

    email, _session_key = await live_session._require_staff_identity()

    assert email == "person@blumountain.me"


@pytest.mark.asyncio
async def test_require_staff_identity_rejects_when_allowlist_empty(monkeypatch):
    """An empty/unconfigured allowlist must fail closed (reject everyone),
    not fail open (admit everyone) — under default-open access this domain
    check is the only gate standing between a stranger and every client's
    HubSpot data."""
    monkeypatch.setattr(live_session, "get_access_token", lambda: _fake_token("person@blumountain.me"))
    monkeypatch.setattr(live_session.settings, "fastmcp_allowed_google_domains", "")
    monkeypatch.setattr(live_session, "record_audit", AsyncMock())

    with pytest.raises(live_session.NotAllowedDomain):
        await live_session._require_staff_identity()


@pytest.mark.asyncio
async def test_require_staff_identity_handles_none_valued_claims(monkeypatch):
    """A claims dict with a key present but valued None (not simply absent)
    must not crash — `.get(key, "")`'s default only applies when the key is
    missing entirely, so `.get(key) or ""` is required to handle both."""
    token = SimpleNamespace(claims={"email": None, "hd": None, "jti": "jti-1"}, token="raw-token")
    monkeypatch.setattr(live_session, "get_access_token", lambda: token)
    monkeypatch.setattr(live_session, "record_audit", AsyncMock())

    with pytest.raises(live_session.NotAllowedDomain):
        await live_session._require_staff_identity()


@pytest.mark.asyncio
async def test_query_hubspot_data_returns_core_crm_objects(monkeypatch):
    """Core CRM objects (contacts, deals, companies, etc.) have no
    per-object tool — reachable only via query_crm_data — so this must not
    silently return {} the way it did before this path was added."""
    envelope = {
        "results": [{"content": json.dumps({"id": "contact-1", "properties": {}})}]
    }
    await _seed_single_tenant(
        "hub_live_a", monkeypatch, ["query_crm_data"], {"query_crm_data": envelope}
    )

    result = await live_session.query_hubspot_data("contacts")

    assert "CONTACT" in result
    assert result["CONTACT"] == [{"id": "contact-1", "properties": {}}]


@pytest.mark.asyncio
async def test_query_hubspot_data_matches_irregular_plural_companies(monkeypatch):
    """"companies" is not a substring of "COMPANY" and vice versa (the
    plural changes "y" to "ies") — a bare substring check misses this
    entirely, silently returning nothing for one of the objects staff
    would ask for most. CRM_OBJECT_ALIASES exists specifically to catch
    this and other irregular/compound names."""
    envelope = {"results": [{"content": json.dumps({"id": "co-1", "properties": {}})}]}
    await _seed_single_tenant(
        "hub_live_companies", monkeypatch, ["query_crm_data"], {"query_crm_data": envelope}
    )

    result = await live_session.query_hubspot_data("companies")

    assert result["COMPANY"] == [{"id": "co-1", "properties": {}}]


@pytest.mark.asyncio
async def test_query_hubspot_data_matches_compound_meeting_event(monkeypatch):
    """"meetings" has no substring relationship with "MEETING_EVENT" at
    all — a compound, underscored type name a plain plural-of-singular
    check can never catch."""
    envelope = {"results": [{"content": json.dumps({"id": "m-1", "properties": {}})}]}
    await _seed_single_tenant(
        "hub_live_meetings", monkeypatch, ["query_crm_data"], {"query_crm_data": envelope}
    )

    result = await live_session.query_hubspot_data("meetings")

    assert result["MEETING_EVENT"] == [{"id": "m-1", "properties": {}}]


@pytest.mark.asyncio
async def test_query_hubspot_data_matches_teams_via_organization_alias(monkeypatch):
    """"teams" has no CRM_OBJECT_TYPES entry at all — its only real path
    is get_organization_details, findable only by translating "teams" to
    "organization" first, the same way hubspot_client.py's own
    IN_SCOPE_OBJECT_KEYWORDS already does for the scheduled pull."""
    await _seed_single_tenant(
        "hub_live_teams",
        monkeypatch,
        ["get_organization_details"],
        {"get_organization_details": {"teams": [{"id": "team-1"}]}},
    )

    result = await live_session.query_hubspot_data("teams")

    assert result["get_organization_details"] == {"teams": [{"id": "team-1"}]}


@pytest.mark.asyncio
async def test_query_hubspot_data_handles_campaign_without_crashing(monkeypatch):
    """read_campaign_data always needs a specific campaignCrmObjectId — a
    bare call with none used to raise uncaught. Campaign queries must
    route through pull_campaign_data()'s enumerate-then-call-per-campaign
    handling instead."""
    campaign_envelope = {
        "results": [{"content": json.dumps({"properties": {"hs_object_id": "111"}})}]
    }
    await _seed_single_tenant(
        "hub_live_b",
        monkeypatch,
        ["query_crm_data", "read_campaign_data"],
        {"query_crm_data": campaign_envelope, "read_campaign_data": {"views": 10}},
    )

    result = await live_session.query_hubspot_data("campaign")

    assert result["campaign_data"] == [{"views": 10, "id": "111"}]


@pytest.mark.asyncio
async def test_query_hubspot_data_still_matches_generic_tools(monkeypatch):
    """The original behavior (matching generic, dynamically-discovered
    tools by substring) must still work for object types that aren't core
    CRM objects or campaigns."""
    await _seed_single_tenant(
        "hub_live_c", monkeypatch, ["search_owners"], {"search_owners": {"owners": []}}
    )

    result = await live_session.query_hubspot_data("owners")

    assert result["search_owners"] == {"owners": []}


@pytest.mark.asyncio
async def test_query_hubspot_data_never_calls_read_campaign_data_bare(monkeypatch):
    """read_campaign_data must be excluded from the generic-tool loop even
    when it matches by substring — it's already handled via
    pull_campaign_data() above, and calling it bare would fail (no
    campaignCrmObjectId)."""
    await _seed_single_tenant(
        "hub_live_d", monkeypatch, ["read_campaign_data"], {"query_crm_data": {"results": []}}
    )

    result = await live_session.query_hubspot_data("campaign")

    assert "read_campaign_data" not in result
    assert result["campaign_data"] == []
