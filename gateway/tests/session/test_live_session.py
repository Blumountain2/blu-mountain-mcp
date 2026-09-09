"""Unit tests for session/live_session.py's staff-identity extraction and
the four category-scoped query_* tools' routing across
sync/hubspot_client.py's three read paths (openspec/changes/separate-
vertical-client-agents, task 6 — replacing the single generic
query_hubspot_data). conftest.py's autouse _pool fixture opens a real
Postgres connection for every test in this suite — there's no
DB-independent test tier here."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastmcp import Client

from db import get_pool
from session import live_session
from sync.hubspot_client import HubSpotDataPullClient


def _fake_token(email: str, hd: str = "blumountain.me", jti: str = "jti-1"):
    """Matches the REAL shape FastMCP's GoogleProvider issues, confirmed by
    reading its source: hd is not a top-level claim, it's nested inside the
    raw Google userinfo response under google_user_data. An earlier version
    of this fake put hd at the top level instead, matching a bug in
    _require_staff_identity rather than reality — every test built on it
    passed while the real domain check silently failed for every real
    login. Don't reintroduce a top-level "hd" key here."""
    return SimpleNamespace(
        claims={"email": email, "google_user_data": {"hd": hd}, "jti": jti},
        token="raw-token",
    )


def _resp(status_code: int, body: dict) -> httpx.Response:
    request = httpx.Request("GET", "https://api.hubapi.com/fake")
    return httpx.Response(status_code, json=body, request=request)


def _page(results: list[dict]) -> httpx.Response:
    return _resp(200, {"results": results, "paging": {}})


class _FakeAsyncClient:
    """Same fake shape as tests/sync/test_hubspot_client.py's own: routes
    GET/POST calls to per-path handler functions against api.hubapi.com,
    since HubSpotDataPullClient is REST-based (openspec/changes/hubspot-
    rest-api-pivot), not MCP-based, as of this rewrite."""

    def __init__(self, get_handlers: dict | None = None, post_handlers: dict | None = None):
        self._get_handlers = get_handlers or {}
        self._post_handlers = post_handlers or {}
        self.calls: list[tuple[str, str, dict, dict]] = []

    def _path(self, url: str) -> str:
        return url.replace("https://api.hubapi.com", "")

    async def get(self, url, headers=None, params=None):
        path = self._path(url)
        self.calls.append(("GET", path, params or {}, headers or {}))
        handler = self._get_handlers.get(path)
        if handler is None:
            raise AssertionError(f"no fake GET handler registered for {path}")
        return handler(params or {})

    async def post(self, url, headers=None, json=None):
        path = self._path(url)
        self.calls.append(("POST", path, json or {}, headers or {}))
        handler = self._post_handlers.get(path)
        if handler is None:
            raise AssertionError(f"no fake POST handler registered for {path}")
        return handler(json or {})

    async def aclose(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


async def _seed_single_tenant(hub_id: str, monkeypatch, get_handlers: dict | None = None, post_handlers: dict | None = None):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'installed')", hub_id
    )

    async def fake_client_for_hub(self):
        return _FakeAsyncClient(get_handlers, post_handlers), {"Authorization": "Bearer access-token"}

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)
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
    missing entirely, so `.get(key) or ""` is required to handle both. Here
    google_user_data itself is None, the realistic case (Google's userinfo
    call failing leaves FastMCP's own user_data dict empty/falsy)."""
    token = SimpleNamespace(
        claims={"email": None, "google_user_data": None, "jti": "jti-1"}, token="raw-token"
    )
    monkeypatch.setattr(live_session, "get_access_token", lambda: token)
    monkeypatch.setattr(live_session, "record_audit", AsyncMock())

    with pytest.raises(live_session.NotAllowedDomain):
        await live_session._require_staff_identity()


@pytest.mark.asyncio
async def test_require_staff_identity_handles_non_dict_google_user_data(monkeypatch):
    """google_user_data present but not a dict (e.g. a string) must fail
    closed with NotAllowedDomain, not crash with AttributeError on
    `.get("hd")` — the `or {}` fallback only guards the falsy case
    (None/missing), not a truthy non-dict value."""
    token = SimpleNamespace(
        claims={"email": "staff@blumountain.me", "google_user_data": "not-a-dict", "jti": "jti-1"},
        token="raw-token",
    )
    monkeypatch.setattr(live_session, "get_access_token", lambda: token)
    monkeypatch.setattr(live_session, "record_audit", AsyncMock())

    with pytest.raises(live_session.NotAllowedDomain):
        await live_session._require_staff_identity()


@pytest.mark.asyncio
async def test_require_staff_identity_reads_hd_from_nested_google_user_data(monkeypatch):
    """Regression test for a real bug found via live use: FastMCP's
    GoogleProvider does NOT put hd at the top level of AccessToken.claims —
    confirmed by reading its source — it's nested inside the raw Google
    userinfo response under claims["google_user_data"]["hd"]. Every real
    login was correctly passing hd through Google's own consent screen and
    callback, but this function read the wrong location and rejected every
    real staff member with "Domain '' is not on the allowlist" until fixed."""
    token = SimpleNamespace(
        claims={
            "email": "staff@blumountain.me",
            "google_user_data": {"hd": "blumountain.me"},
            "jti": "jti-1",
        },
        token="raw-token",
    )
    monkeypatch.setattr(live_session, "get_access_token", lambda: token)

    email, _session_key = await live_session._require_staff_identity()

    assert email == "staff@blumountain.me"


@pytest.mark.asyncio
async def test_require_staff_identity_still_accepts_top_level_hd_if_ever_present(monkeypatch):
    """Defensive: if a future FastMCP version ever puts hd back at the top
    level of claims, that must still work — the nested google_user_data
    lookup is a fallback for the current real shape, not the only path."""
    token = SimpleNamespace(
        claims={"email": "staff@blumountain.me", "hd": "blumountain.me", "jti": "jti-1"},
        token="raw-token",
    )
    monkeypatch.setattr(live_session, "get_access_token", lambda: token)

    email, _session_key = await live_session._require_staff_identity()

    assert email == "staff@blumountain.me"


async def _seed_named_tenant(
    hub_id: str, monkeypatch, portal_name: str | None = None, hub_domain: str | None = None,
    email: str = "staff@blumountain.me",
):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id, portal_name, hub_domain, install_status) "
        "VALUES ($1, $2, $3, 'installed')",
        hub_id, portal_name, hub_domain,
    )
    monkeypatch.setattr(live_session, "get_access_token", lambda: _fake_token(email))
    monkeypatch.setattr(live_session, "record_audit", AsyncMock())


@pytest.mark.asyncio
async def test_list_my_tenants_returns_hub_id_and_name(monkeypatch):
    await _seed_named_tenant("hub_named_a", monkeypatch, portal_name="Blu Mountain & Gumpper")
    await _seed_named_tenant("hub_named_b", monkeypatch, hub_domain="blu-mountain-test.example.com")
    await _seed_named_tenant("hub_named_c", monkeypatch)

    tenants = await live_session.list_my_tenants()

    by_id = {t["hub_id"]: t["name"] for t in tenants}
    assert by_id["hub_named_a"] == "Blu Mountain & Gumpper"
    assert by_id["hub_named_b"] == "blu-mountain-test.example.com"
    # Neither portal_name nor hub_domain set — falls back to the bare
    # hub_id, never NULL, never crashes.
    assert by_id["hub_named_c"] == "hub_named_c"


@pytest.mark.asyncio
async def test_list_my_tenants_treats_blank_portal_name_as_missing(monkeypatch):
    # Defense in depth on the read side: an empty/whitespace-only
    # portal_name (e.g. from data written before the write-side normalization
    # existed, or any other path that didn't go through it) must still fall
    # through to hub_domain — a bare COALESCE would treat "" as "the name".
    await _seed_named_tenant(
        "hub_blank_name", monkeypatch, portal_name="   ", hub_domain="blumountain.me"
    )

    tenants = await live_session.list_my_tenants()

    by_id = {t["hub_id"]: t["name"] for t in tenants}
    assert by_id["hub_blank_name"] == "blumountain.me"


@pytest.mark.asyncio
async def test_select_tenant_by_exact_hub_id(monkeypatch):
    await _seed_named_tenant("hub_select_a", monkeypatch, portal_name="Blu Mountain & Gumpper")

    result = await live_session.select_tenant("hub_select_a")

    assert result == {"selected_hub_id": "hub_select_a", "name": "Blu Mountain & Gumpper"}


@pytest.mark.asyncio
async def test_select_tenant_by_exact_name(monkeypatch):
    await _seed_named_tenant("hub_select_b", monkeypatch, portal_name="Blu Mountain & Gumpper")

    result = await live_session.select_tenant("Blu Mountain & Gumpper")

    assert result["selected_hub_id"] == "hub_select_b"


@pytest.mark.asyncio
async def test_select_tenant_by_name_is_case_insensitive_substring(monkeypatch):
    await _seed_named_tenant("hub_select_c", monkeypatch, portal_name="Blu Mountain & Gumpper")

    result = await live_session.select_tenant("blu mountain")

    assert result["selected_hub_id"] == "hub_select_c"


@pytest.mark.asyncio
async def test_select_tenant_ambiguous_name_returns_candidates_not_a_guess(monkeypatch):
    """The actual scenario this feature exists for: two tenants with
    closely-resembling names must never be silently disambiguated — a wrong
    guess here is a real cross-tenant risk under default-open access."""
    await _seed_named_tenant("hub_ambig_a", monkeypatch, portal_name="Blu Mountain & Gumpper")
    await _seed_named_tenant("hub_ambig_b", monkeypatch, portal_name="Blu Mountain - Test Account")

    result = await live_session.select_tenant("Blu Mountain")

    assert result["ambiguous"] is True
    assert result["query"] == "Blu Mountain"
    candidate_ids = {c["hub_id"] for c in result["candidates"]}
    assert candidate_ids == {"hub_ambig_a", "hub_ambig_b"}

    # Nothing gets selected when ambiguous.
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT selected_hub_id FROM live_session_selection WHERE staff_identity = $1",
        "staff@blumountain.me",
    )
    assert row is None


@pytest.mark.asyncio
async def test_select_tenant_no_match_raises_not_permitted(monkeypatch):
    await _seed_named_tenant("hub_nomatch", monkeypatch, portal_name="Blu Mountain & Gumpper")

    with pytest.raises(live_session.TenantNotPermitted):
        await live_session.select_tenant("Totally Unrelated Company")


@pytest.mark.asyncio
async def test_select_tenant_ambiguous_candidates_never_include_a_restricted_tenant(monkeypatch):
    """Cross-tenant isolation for the ambiguity feature: matching only ever
    iterates the caller's already-restriction-filtered permitted set, never
    a raw tenants query — a restricted tenant's name must never leak into
    another staff member's ambiguous-candidates list, even when it would
    otherwise match."""
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id, portal_name, install_status) VALUES ($1, $2, 'installed')",
        "hub_restricted_x", "Blu Mountain & Gumpper",
    )
    await pool.execute(
        "INSERT INTO tenants (hub_id, portal_name, install_status) VALUES ($1, $2, 'installed')",
        "hub_allowed_x", "Blu Mountain - Test Account",
    )
    await pool.execute(
        "INSERT INTO staff_tenant_restrictions (staff_identity, hub_id) VALUES ($1, $2)",
        "restricted-staff@blumountain.me", "hub_restricted_x",
    )
    monkeypatch.setattr(
        live_session, "get_access_token", lambda: _fake_token("restricted-staff@blumountain.me")
    )
    monkeypatch.setattr(live_session, "record_audit", AsyncMock())

    result = await live_session.select_tenant("Blu Mountain")

    # Only one match remains once the restricted tenant is filtered out —
    # not ambiguous at all, and definitely not leaking the restricted name.
    assert result.get("ambiguous") is not True
    assert result["selected_hub_id"] == "hub_allowed_x"


@pytest.mark.asyncio
async def test_query_users_never_constructs_a_client_for_a_restricted_tenant(monkeypatch):
    """Strengthens the "no data leakage" guarantee beyond "the right
    exception was raised somewhere upstream" (which every other isolation
    test proves): this asserts the actual HubSpot-pulling client is only
    ever constructed for the permitted tenant, never for the one this
    staff member is restricted from — the concrete thing "no leakage"
    actually means, not just an inference from a raised exception."""
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'installed')",
        "hub_leak_restricted",
    )
    await pool.execute(
        "INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'installed')",
        "hub_leak_allowed",
    )
    await pool.execute(
        "INSERT INTO staff_tenant_restrictions (staff_identity, hub_id) VALUES ($1, $2)",
        "leak-check@blumountain.me", "hub_leak_restricted",
    )
    monkeypatch.setattr(
        live_session, "get_access_token", lambda: _fake_token("leak-check@blumountain.me")
    )
    monkeypatch.setattr(live_session, "record_audit", AsyncMock())

    constructed_hub_ids = []
    real_init = HubSpotDataPullClient.__init__

    def _recording_init(self, hub_id):
        constructed_hub_ids.append(hub_id)
        real_init(self, hub_id)

    monkeypatch.setattr(HubSpotDataPullClient, "__init__", _recording_init)

    async def fake_client_for_hub(self):
        return _FakeAsyncClient(get_handlers={"/crm/v3/owners/": lambda params: _page([])}), {
            "Authorization": "Bearer access-token"
        }

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    await live_session.query_users("owners")

    # The only tenant with only one permitted match auto-selects — the
    # HubSpot client was constructed exactly once, and only ever for the
    # permitted tenant. The restricted tenant's hub_id never appears here,
    # not because an exception happened to fire first, but because nothing
    # in this call chain can ever reach it.
    assert constructed_hub_ids == ["hub_leak_allowed"]
    assert "hub_leak_restricted" not in constructed_hub_ids


@pytest.mark.asyncio
async def test_query_crm_records_returns_core_crm_objects(monkeypatch):
    """Core CRM objects (contacts, deals, companies, etc.) have no
    dedicated generic capability — reachable only via
    /crm/v3/objects/{slug} — so this must not silently return {} the way
    it did before this path was added."""
    await _seed_single_tenant(
        "hub_live_a",
        monkeypatch,
        get_handlers={"/crm/v3/objects/contacts": lambda params: _page([{"id": "contact-1", "properties": {}}])},
    )

    result = await live_session.query_crm_records("contacts")

    assert "CONTACT" in result
    assert result["CONTACT"] == [{"id": "contact-1", "properties": {}}]


@pytest.mark.asyncio
async def test_query_crm_records_matches_irregular_plural_companies(monkeypatch):
    """"companies" is not a substring of "COMPANY" and vice versa (the
    plural changes "y" to "ies") — a bare substring check misses this
    entirely, silently returning nothing for one of the objects staff
    would ask for most. CRM_OBJECT_ALIASES exists specifically to catch
    this and other irregular/compound names."""
    await _seed_single_tenant(
        "hub_live_companies",
        monkeypatch,
        get_handlers={"/crm/v3/objects/companies": lambda params: _page([{"id": "co-1", "properties": {}}])},
    )

    result = await live_session.query_crm_records("companies")

    assert result["COMPANY"] == [{"id": "co-1", "properties": {}}]


@pytest.mark.asyncio
async def test_query_crm_records_can_be_scoped_to_explicit_properties(monkeypatch):
    """task 6.3: an explicit properties list is forwarded through to
    pull_crm_objects, which is what lets a category tool be scoped to a
    client's own confirmed-relevant or custom fields — confirmed live
    (openspec/changes/hubspot-rest-api-pivot, task 2.3) this narrows the
    REST response to exactly those properties, not additively."""
    seen_params = {}

    def contacts_handler(params):
        seen_params["contacts"] = params
        return _page([{"id": "contact-1", "properties": {}}])

    await _seed_single_tenant(
        "hub_live_props", monkeypatch, get_handlers={"/crm/v3/objects/contacts": contacts_handler}
    )

    await live_session.query_crm_records("contacts", properties=["email", "custom_lead_score"])

    assert seen_params["contacts"]["properties"] == "email,custom_lead_score"


@pytest.mark.asyncio
async def test_query_crm_records_rejects_an_out_of_category_object_type(monkeypatch):
    """task 6.1: a real object type that belongs to a different category
    tool is rejected explicitly, not silently returned empty — "calls" is
    an Engagement Record, not a CRM Record."""
    await _seed_single_tenant("hub_live_wrong_cat", monkeypatch)

    result = await live_session.query_crm_records("calls")

    assert "error" in result
    assert "CONTACT" not in result


@pytest.mark.asyncio
async def test_query_engagement_records_matches_compound_meeting_event(monkeypatch):
    """"meetings" has no substring relationship with "MEETING_EVENT" at
    all — a compound, underscored type name a plain plural-of-singular
    check can never catch."""
    await _seed_single_tenant(
        "hub_live_meetings",
        monkeypatch,
        get_handlers={"/crm/v3/objects/meetings": lambda params: _page([{"id": "m-1", "properties": {}}])},
    )

    result = await live_session.query_engagement_records("meetings")

    assert result["MEETING_EVENT"] == [{"id": "m-1", "properties": {}}]


@pytest.mark.asyncio
async def test_query_users_matches_teams_via_organization_alias(monkeypatch):
    """"teams" has no CRM_OBJECT_TYPES entry at all — its only real path
    is the organization_details capability, findable only by translating
    "teams" to "organization" first, the same way hubspot_client.py's own
    generic-capability categorization already does for the scheduled
    pull."""
    await _seed_single_tenant(
        "hub_live_teams",
        monkeypatch,
        get_handlers={
            "/settings/v3/users/teams": lambda params: _resp(200, {"results": [{"id": "team-1"}]}),
            "/settings/v3/users/": lambda params: _resp(200, {}),
            "/account-info/v3/details": lambda params: _resp(200, {}),
        },
    )

    result = await live_session.query_users("teams")

    assert result["organization_details"]["teams"] == {"results": [{"id": "team-1"}]}


@pytest.mark.asyncio
async def test_query_marketing_content_handles_campaign_without_crashing(monkeypatch):
    """Every per-campaign metrics call needs a specific campaign GUID —
    campaign queries must route through pull_campaign_data()'s
    enumerate-then-call-per-campaign handling, not a bare call with no
    ID."""
    await _seed_single_tenant(
        "hub_live_b",
        monkeypatch,
        get_handlers={
            "/marketing/v3/campaigns": lambda params: _page([{"id": "111"}]),
            "/marketing/v3/campaigns/111/reports/metrics": lambda params: _resp(200, {"views": 10}),
        },
    )

    result = await live_session.query_marketing_content("campaign")

    assert result["campaign_data"] == [{"views": 10, "id": "111"}]


@pytest.mark.asyncio
async def test_query_users_still_matches_generic_tools(monkeypatch):
    """The original behavior (matching generic capabilities by substring)
    must still work for object types that aren't core CRM objects or
    campaigns."""
    await _seed_single_tenant(
        "hub_live_c", monkeypatch, get_handlers={"/crm/v3/owners/": lambda params: _page([])}
    )

    result = await live_session.query_users("owners")

    assert result["owners"] == []


@pytest.mark.asyncio
async def test_query_crm_records_never_matches_a_generic_tool_from_another_category(monkeypatch):
    """The "owners" capability belongs to the Users category tool only —
    a CRM Records query for "owners" (no CRM_OBJECT_TYPES match either)
    must come back empty, not reach across categories."""
    await _seed_single_tenant(
        "hub_live_cross_cat", monkeypatch, get_handlers={"/crm/v3/owners/": lambda params: _page([])}
    )

    result = await live_session.query_crm_records("owners")

    assert result == {}


@pytest.mark.asyncio
async def test_list_custom_objects_returns_real_schemas(monkeypatch):
    """Custom objects (task 4/5, gateway/scripts/generate_confirmed_fields.py
    conversation, 2026-09-08) have no fixed lookup table the way standard
    CRM object types do — a caller must discover a tenant's real schemas
    first, the same "list, then pull by objectTypeId" shape debug_api.py's
    /custom-objects routes and BaseAgent's list_custom_objects/
    pull_custom_object tool pair already use."""
    await _seed_single_tenant(
        "hub_live_custom_schemas",
        monkeypatch,
        get_handlers={
            "/crm-object-schemas/v3/schemas": lambda params: _resp(
                200,
                {"results": [{"objectTypeId": "2-3465404", "name": "transaction", "labels": {"singular": "Transaction"}}]},
            )
        },
    )

    result = await live_session.list_custom_objects()

    assert result == [{"objectTypeId": "2-3465404", "name": "transaction", "labels": {"singular": "Transaction"}}]


def _custom_schemas_handler(schemas: list[dict]):
    return lambda params: _resp(200, {"results": schemas})


_TXN_SCHEMA = {"objectTypeId": "2-3465404", "name": "transaction", "labels": {"singular": "Transaction", "plural": "Transactions"}}


@pytest.mark.asyncio
async def test_query_custom_object_returns_real_records_by_exact_object_type_id(monkeypatch):
    await _seed_single_tenant(
        "hub_live_custom_pull",
        monkeypatch,
        get_handlers={
            "/crm-object-schemas/v3/schemas": _custom_schemas_handler([_TXN_SCHEMA]),
            "/crm/v3/objects/2-3465404": lambda params: _page([{"id": "txn-1", "properties": {}}]),
        },
    )

    result = await live_session.query_custom_object("2-3465404")

    assert result == {"object_type_id": "2-3465404", "records": [{"id": "txn-1", "properties": {}}]}


@pytest.mark.asyncio
async def test_query_custom_object_resolves_a_friendly_name(monkeypatch):
    """No fixed alias table for custom objects (unlike standard CRM object
    types) — resolution always goes through this tenant's own real, live
    schema data instead, matched case-insensitively against name/labels."""
    await _seed_single_tenant(
        "hub_live_custom_name",
        monkeypatch,
        get_handlers={
            "/crm-object-schemas/v3/schemas": _custom_schemas_handler([_TXN_SCHEMA]),
            "/crm/v3/objects/2-3465404": lambda params: _page([{"id": "txn-1", "properties": {}}]),
        },
    )

    result = await live_session.query_custom_object("Transactions")

    assert result == {"object_type_id": "2-3465404", "records": [{"id": "txn-1", "properties": {}}]}


@pytest.mark.asyncio
async def test_query_custom_object_ambiguous_name_returns_candidates_not_a_guess(monkeypatch):
    other_schema = {"objectTypeId": "2-9999999", "name": "transaction_v2", "labels": {"singular": "Transaction", "plural": "Transactionz"}}
    await _seed_single_tenant(
        "hub_live_custom_ambiguous",
        monkeypatch,
        get_handlers={"/crm-object-schemas/v3/schemas": _custom_schemas_handler([_TXN_SCHEMA, other_schema])},
    )

    result = await live_session.query_custom_object("Transaction")

    assert result["ambiguous"] is True
    assert {c["objectTypeId"] for c in result["candidates"]} == {"2-3465404", "2-9999999"}


@pytest.mark.asyncio
async def test_query_custom_object_no_match_returns_a_clear_error(monkeypatch):
    await _seed_single_tenant(
        "hub_live_custom_no_match",
        monkeypatch,
        get_handlers={"/crm-object-schemas/v3/schemas": _custom_schemas_handler([_TXN_SCHEMA])},
    )

    result = await live_session.query_custom_object("Nonexistent Object")

    assert "error" in result
    assert "records" not in result


@pytest.mark.asyncio
async def test_query_custom_object_can_be_scoped_to_explicit_properties(monkeypatch):
    """Mirrors test_query_crm_records_can_be_scoped_to_explicit_properties —
    the same explicit-narrowing behavior, for a custom object's own
    properties endpoint."""
    seen_params = {}

    def handler(params):
        seen_params["txn"] = params
        return _page([{"id": "txn-1", "properties": {}}])

    await _seed_single_tenant(
        "hub_live_custom_props",
        monkeypatch,
        get_handlers={
            "/crm-object-schemas/v3/schemas": _custom_schemas_handler([_TXN_SCHEMA]),
            "/crm/v3/objects/2-3465404": handler,
        },
    )

    await live_session.query_custom_object("2-3465404", properties=["status", "amount"])

    assert seen_params["txn"]["properties"] == "status,amount"


@pytest.mark.asyncio
async def test_list_custom_objects_never_constructs_a_client_for_a_restricted_tenant(monkeypatch):
    """Same isolation guarantee as test_query_users_never_constructs_a_client_for_a_restricted_tenant,
    proven for the new custom-object tools specifically — the actual
    HubSpot-pulling client is only ever constructed for the permitted
    tenant."""
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'installed')",
        "hub_custom_leak_restricted",
    )
    await pool.execute(
        "INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'installed')",
        "hub_custom_leak_allowed",
    )
    await pool.execute(
        "INSERT INTO staff_tenant_restrictions (staff_identity, hub_id) VALUES ($1, $2)",
        "custom-leak-check@blumountain.me", "hub_custom_leak_restricted",
    )
    monkeypatch.setattr(
        live_session, "get_access_token", lambda: _fake_token("custom-leak-check@blumountain.me")
    )
    monkeypatch.setattr(live_session, "record_audit", AsyncMock())

    constructed_hub_ids = []
    real_init = HubSpotDataPullClient.__init__

    def _recording_init(self, hub_id):
        constructed_hub_ids.append(hub_id)
        real_init(self, hub_id)

    monkeypatch.setattr(HubSpotDataPullClient, "__init__", _recording_init)

    async def fake_client_for_hub(self):
        return _FakeAsyncClient(get_handlers={"/crm-object-schemas/v3/schemas": lambda params: _page([])}), {
            "Authorization": "Bearer access-token"
        }

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    await live_session.list_custom_objects()

    assert constructed_hub_ids == ["hub_custom_leak_allowed"]
    assert "hub_custom_leak_restricted" not in constructed_hub_ids


@pytest.mark.asyncio
async def test_query_custom_object_never_constructs_a_client_for_a_restricted_tenant(monkeypatch):
    """Same isolation guarantee, proven for query_custom_object specifically —
    not just its sibling list_custom_objects. query_custom_object makes two
    real HubSpot calls internally (resolve, then pull); both must only ever
    happen against the permitted tenant."""
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'installed')",
        "hub_custom_pull_leak_restricted",
    )
    await pool.execute(
        "INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'installed')",
        "hub_custom_pull_leak_allowed",
    )
    await pool.execute(
        "INSERT INTO staff_tenant_restrictions (staff_identity, hub_id) VALUES ($1, $2)",
        "custom-pull-leak-check@blumountain.me", "hub_custom_pull_leak_restricted",
    )
    monkeypatch.setattr(
        live_session, "get_access_token", lambda: _fake_token("custom-pull-leak-check@blumountain.me")
    )
    monkeypatch.setattr(live_session, "record_audit", AsyncMock())

    constructed_hub_ids = []
    real_init = HubSpotDataPullClient.__init__

    def _recording_init(self, hub_id):
        constructed_hub_ids.append(hub_id)
        real_init(self, hub_id)

    monkeypatch.setattr(HubSpotDataPullClient, "__init__", _recording_init)

    async def fake_client_for_hub(self):
        return _FakeAsyncClient(
            get_handlers={
                "/crm-object-schemas/v3/schemas": _custom_schemas_handler([_TXN_SCHEMA]),
                "/crm/v3/objects/2-3465404": lambda params: _page([{"id": "txn-1", "properties": {}}]),
            }
        ), {"Authorization": "Bearer access-token"}

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    await live_session.query_custom_object("2-3465404")

    assert constructed_hub_ids == ["hub_custom_pull_leak_allowed"]
    assert "hub_custom_pull_leak_restricted" not in constructed_hub_ids


# Every test above calls live_session's plain async functions directly —
# real, but it never exercises the actual MCP transport layer itself: tool
# discovery, JSON-RPC parameter binding, or result (de)serialization. A
# renamed parameter (e.g. select_tenant's hub_id -> tenant) or a
# non-serializable return value would still pass every test above while
# being broken for any real MCP client. These use a real fastmcp.Client
# connected in-memory to the actual live_session.mcp server object — the
# same class of test used to verify the FastMCP 4.0/MCP SDK 2.0 upgrade
# earlier, applied here to the live session's own tool surface. Auth is
# stubbed the same way as every other test (monkeypatching
# get_access_token) — confirmed live that an in-memory Client connection
# never reaches GoogleProvider's HTTP-level OAuth challenge at all, so this
# is not weakened by stubbing that one piece.


@pytest.mark.asyncio
async def test_real_transport_lists_all_eight_tools_with_correct_schemas(monkeypatch):
    """Catches a parameter-rename regression class of bug that every other
    test in this file cannot: those call Python functions directly by
    keyword, so a mismatch between the function's real parameter name and
    what a client's tool schema advertises would never surface. This goes
    through real tool discovery instead."""
    monkeypatch.setattr(
        live_session, "get_access_token", lambda: _fake_token("staff@blumountain.me")
    )
    monkeypatch.setattr(live_session, "record_audit", AsyncMock())

    async with Client(live_session.mcp) as client:
        tools = await client.list_tools()

    by_name = {t.name: set((t.input_schema or {}).get("properties", {}).keys()) for t in tools}
    assert by_name == {
        "list_my_tenants": set(),
        "select_tenant": {"tenant"},
        "query_crm_records": {"object_type", "properties"},
        "query_engagement_records": {"object_type", "properties"},
        "query_marketing_content": {"object_type", "properties"},
        "query_users": {"object_type", "properties"},
        "list_custom_objects": set(),
        "query_custom_object": {"object_type", "properties"},
    }


@pytest.mark.asyncio
async def test_real_transport_list_my_tenants_and_select_tenant_round_trip(monkeypatch):
    """A real call_tool round trip — real JSON-RPC request, real parameter
    binding by name, real result serialization/deserialization — not just
    a direct Python call with keyword arguments that happen to line up."""
    await _seed_named_tenant("hub_transport_a", monkeypatch, portal_name="Real Transport Test")

    async with Client(live_session.mcp) as client:
        list_result = await client.call_tool("list_my_tenants", {})
        select_result = await client.call_tool("select_tenant", {"tenant": "Real Transport Test"})

    assert list_result.data == [{"hub_id": "hub_transport_a", "name": "Real Transport Test"}]
    assert select_result.data == {"selected_hub_id": "hub_transport_a", "name": "Real Transport Test"}


@pytest.mark.asyncio
async def test_real_transport_query_users_round_trip(monkeypatch):
    await _seed_single_tenant(
        "hub_transport_b",
        monkeypatch,
        get_handlers={"/crm/v3/owners/": lambda params: _page([])},
    )

    async with Client(live_session.mcp) as client:
        result = await client.call_tool("query_users", {"object_type": "owners"})

    assert result.data == {"owners": []}


@pytest.mark.asyncio
async def test_real_transport_query_crm_records_with_properties_round_trip(monkeypatch):
    """A real call_tool round trip exercising the new `properties`
    parameter specifically — confirms it's wired through real JSON-RPC
    parameter binding, not just a direct Python keyword call."""
    await _seed_single_tenant(
        "hub_transport_props",
        monkeypatch,
        get_handlers={"/crm/v3/objects/contacts": lambda params: _page([{"id": "contact-1", "properties": {}}])},
    )

    async with Client(live_session.mcp) as client:
        result = await client.call_tool(
            "query_crm_records", {"object_type": "contacts", "properties": ["email"]}
        )

    assert result.data["CONTACT"] == [{"id": "contact-1", "properties": {}}]


@pytest.mark.asyncio
async def test_real_transport_query_engagement_records_rejects_out_of_category_type(monkeypatch):
    await _seed_single_tenant("hub_transport_wrong_cat", monkeypatch)

    async with Client(live_session.mcp) as client:
        result = await client.call_tool("query_engagement_records", {"object_type": "contacts"})

    assert "error" in result.data


@pytest.mark.asyncio
async def test_real_transport_list_custom_objects_round_trip(monkeypatch):
    await _seed_single_tenant(
        "hub_transport_custom_list",
        monkeypatch,
        get_handlers={
            "/crm-object-schemas/v3/schemas": lambda params: _resp(
                200, {"results": [{"objectTypeId": "2-3465404", "name": "transaction", "labels": {"singular": "Transaction"}}]}
            )
        },
    )

    async with Client(live_session.mcp) as client:
        result = await client.call_tool("list_custom_objects", {})

    assert result.data == [{"objectTypeId": "2-3465404", "name": "transaction", "labels": {"singular": "Transaction"}}]


@pytest.mark.asyncio
async def test_real_transport_query_custom_object_round_trip(monkeypatch):
    """Exercises the object_type/properties parameters specifically
    through real JSON-RPC parameter binding, not just a direct Python
    keyword call — including resolving a friendly name, not just the
    exact objectTypeId, over real transport."""
    await _seed_single_tenant(
        "hub_transport_custom_pull",
        monkeypatch,
        get_handlers={
            "/crm-object-schemas/v3/schemas": _custom_schemas_handler([_TXN_SCHEMA]),
            "/crm/v3/objects/2-3465404": lambda params: _page([{"id": "txn-1", "properties": {}}]),
        },
    )

    async with Client(live_session.mcp) as client:
        result = await client.call_tool(
            "query_custom_object", {"object_type": "Transactions", "properties": ["status"]}
        )

    assert result.data == {"object_type_id": "2-3465404", "records": [{"id": "txn-1", "properties": {}}]}


@pytest.mark.asyncio
async def test_real_transport_lists_both_prompts_with_correct_schemas():
    async with Client(live_session.mcp) as client:
        prompts = await client.list_prompts()

    by_name = {p.name: {a.name for a in (p.arguments or [])} for p in prompts}
    assert by_name == {
        "tenant_pipeline_overview": {"tenant"},
        "tenant_recent_activity": {"tenant"},
    }


@pytest.mark.asyncio
async def test_real_transport_tenant_pipeline_overview_prompt_round_trip():
    async with Client(live_session.mcp) as client:
        result = await client.get_prompt("tenant_pipeline_overview", {"tenant": "Acme"})

    assert len(result.messages) == 1
    text = result.messages[0].content.text
    assert "Acme" in text
    assert "select_tenant" in text
    assert "query_crm_records" in text


@pytest.mark.asyncio
async def test_real_transport_tenant_recent_activity_prompt_round_trip():
    async with Client(live_session.mcp) as client:
        result = await client.get_prompt("tenant_recent_activity", {"tenant": "Acme"})

    assert len(result.messages) == 1
    text = result.messages[0].content.text
    assert "Acme" in text
    assert "calls" in text and "emails" in text and "meetings" in text
