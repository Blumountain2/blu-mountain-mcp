"""Proves a per-tenant HubSpot pull (REST-based, api.hubapi.com — see
openspec/changes/hubspot-rest-api-pivot) produces a complete read-only
snapshot with no cross-tenant token or data leakage, and that only
recognized capability names can be dispatched. Uses a fake httpx.AsyncClient,
no real HubSpot connection — matching test_hubspot_oauth.py's own use of
bare httpx.Response objects, extended here to a small routing fake since
HubSpotDataPullClient issues several distinct calls per pull rather than one."""

import httpx
import pytest

from sync import hubspot_client
from sync.hubspot_client import HubSpotDataPullClient, HubSpotRateLimited, ReadOnlyViolation


def _resp(status_code: int, body: dict) -> httpx.Response:
    request = httpx.Request("GET", "https://api.hubapi.com/fake")
    return httpx.Response(status_code, json=body, request=request)


def _page(results: list[dict], next_after: str | None = None) -> httpx.Response:
    paging = {"next": {"after": next_after}} if next_after else {}
    return _resp(200, {"results": results, "paging": paging})


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in: dispatches GET/POST calls to
    per-path handler functions, recording every call for assertions.
    Handlers receive the call's params/json body and return an
    httpx.Response — same shape asyncio callers see from the real thing."""

    def __init__(self, get_handlers: dict | None = None, post_handlers: dict | None = None):
        self._get_handlers = get_handlers or {}
        self._post_handlers = post_handlers or {}
        self.calls: list[tuple[str, str, dict, dict]] = []

    def _path(self, url: str) -> str:
        return url.replace(hubspot_client.HUBSPOT_API_BASE, "")

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


def _patch_client_for_hub(monkeypatch, client_factory, token_log: dict | None = None):
    """client_factory: hub_id -> _FakeAsyncClient. Patches _client_for_hub
    (the owns-client path every pull method takes when called with no
    explicit `client=`) so tests never touch a real vault or real HubSpot.
    token_log, when given, records which hub_id each fake client's headers
    were built for — what the isolation tests below check."""

    async def fake_client_for_hub(self):
        fake = client_factory(self.hub_id)
        headers = {"Authorization": f"Bearer access-token-for-{self.hub_id}"}
        if token_log is not None:
            token_log.setdefault(self.hub_id, []).append(headers["Authorization"])
        return fake, headers

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)


def _assert_tokens_never_cross(token_log: dict[str, list[str]]) -> None:
    """Shared by every "only uses this tenant's token" isolation test in
    this file."""
    assert token_log["hub_a"] == ["Bearer access-token-for-hub_a"]
    assert token_log["hub_b"] == ["Bearer access-token-for-hub_b"]
    assert "Bearer access-token-for-hub_b" not in token_log["hub_a"]
    assert "Bearer access-token-for-hub_a" not in token_log["hub_b"]


# --- pull_crm_objects: standard object types via /crm/v3/objects/{slug} ---


@pytest.mark.asyncio
async def test_pull_crm_objects_queries_every_standard_object_type(monkeypatch):
    seen_paths: list[str] = []

    def factory(hub_id):
        def handler(params):
            return _page([{"id": "1", "properties": {}}])

        client = _FakeAsyncClient(get_handlers={f"/crm/v3/objects/{slug}": handler for slug in hubspot_client.CRM_OBJECT_REST_SLUGS.values()})
        return client

    _patch_client_for_hub(monkeypatch, factory)

    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_crm_objects(object_types=list(hubspot_client.CRM_OBJECT_REST_SLUGS.keys()))

    assert set(result.keys()) == set(hubspot_client.CRM_OBJECT_REST_SLUGS.keys())
    for object_type, records in result.items():
        assert records == [{"id": "1", "properties": {}}]


@pytest.mark.asyncio
async def test_pull_crm_objects_follows_pagination():
    fake = _FakeAsyncClient(
        get_handlers={
            "/crm/v3/objects/contacts": lambda params: (
                _page([{"id": "1"}], next_after="cursor-2") if params.get("after") is None else _page([{"id": "2"}])
            )
        }
    )
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_crm_objects(client=fake, headers={}, object_types=["CONTACT"], properties={})

    assert result["CONTACT"] == [{"id": "1"}, {"id": "2"}]
    assert [c[2].get("after") for c in fake.calls] == [None, "cursor-2"]


@pytest.mark.asyncio
async def test_pull_crm_objects_pull_failure_for_one_type_does_not_leak_into_others():
    def contacts_handler(params):
        raise RuntimeError("simulated upstream failure")

    def companies_handler(params):
        return _page([{"id": "c-1"}])

    fake = _FakeAsyncClient(
        get_handlers={
            "/crm/v3/objects/contacts": contacts_handler,
            "/crm/v3/objects/companies": companies_handler,
        }
    )
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_crm_objects(client=fake, headers={}, object_types=["CONTACT", "COMPANY"])

    assert result["CONTACT"] == {"error": "pull_failed"}
    assert result["COMPANY"] == [{"id": "c-1"}]


@pytest.mark.asyncio
async def test_pull_crm_objects_treats_429_as_pull_failed_not_a_crash():
    def rate_limited(params):
        return _resp(429, {})

    fake = _FakeAsyncClient(get_handlers={"/crm/v3/objects/contacts": rate_limited})
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_crm_objects(client=fake, headers={}, object_types=["CONTACT"])

    assert result["CONTACT"] == {"error": "pull_failed"}


@pytest.mark.asyncio
async def test_pull_crm_objects_uses_explicit_properties_when_given():
    seen_params = {}

    def contacts_handler(params):
        seen_params["CONTACT"] = params
        return _page([])

    def companies_handler(params):
        seen_params["COMPANY"] = params
        return _page([])

    fake = _FakeAsyncClient(
        get_handlers={
            "/crm/v3/objects/contacts": contacts_handler,
            "/crm/v3/objects/companies": companies_handler,
        }
    )
    client = HubSpotDataPullClient("hub_a")
    await client.pull_crm_objects(
        client=fake, headers={},
        object_types=["CONTACT", "COMPANY"],
        properties={"CONTACT": ["email", "custom_lead_score"]},
    )

    assert seen_params["CONTACT"]["properties"] == "email,custom_lead_score"
    # COMPANY had no entry in properties — no properties param sent at all,
    # so HubSpot returns its own default set (unchanged behavior).
    assert "properties" not in seen_params["COMPANY"]


@pytest.mark.asyncio
async def test_pull_crm_objects_property_selection_is_exclusive_not_additive():
    """Real behavior change from the prior MCP-based mechanism, confirmed
    live (openspec/changes/hubspot-rest-api-pivot, task 2.3): REST's
    properties= param narrows the response to exactly the requested
    fields, not additively alongside the default set. This test locks in
    the request shape that produces that: exactly the requested names, no
    default-set names mixed in."""
    seen_params = {}

    def handler(params):
        seen_params["CONTACT"] = params
        return _page([{"id": "1", "properties": {"jobtitle": "CEO"}}])

    fake = _FakeAsyncClient(get_handlers={"/crm/v3/objects/contacts": handler})
    client = HubSpotDataPullClient("hub_a")
    await client.pull_crm_objects(client=fake, headers={}, object_types=["CONTACT"], properties={"CONTACT": ["jobtitle"]})

    assert seen_params["CONTACT"]["properties"] == "jobtitle"


@pytest.mark.asyncio
async def test_pull_crm_objects_falls_back_to_default_when_properties_list_is_empty():
    seen_params = {}

    def handler(params):
        seen_params["CONTACT"] = params
        return _page([])

    fake = _FakeAsyncClient(get_handlers={"/crm/v3/objects/contacts": handler})
    client = HubSpotDataPullClient("hub_a")
    await client.pull_crm_objects(client=fake, headers={}, object_types=["CONTACT"], properties={"CONTACT": []})

    assert "properties" not in seen_params["CONTACT"]


@pytest.mark.asyncio
async def test_pull_crm_objects_filters_unsafe_property_names_defensively():
    seen_params = {}

    def handler(params):
        seen_params["CONTACT"] = params
        return _page([])

    fake = _FakeAsyncClient(get_handlers={"/crm/v3/objects/contacts": handler})
    client = HubSpotDataPullClient("hub_a")
    await client.pull_crm_objects(
        client=fake, headers={}, object_types=["CONTACT"], properties={"CONTACT": ["email", "bad; name"]}
    )

    assert seen_params["CONTACT"]["properties"] == "email"


@pytest.mark.asyncio
async def test_pull_uses_only_this_tenants_token_never_anothers(monkeypatch):
    token_log: dict[str, list[str]] = {}

    def factory(hub_id):
        return _FakeAsyncClient(get_handlers={"/crm/v3/objects/contacts": lambda params: _page([])})

    _patch_client_for_hub(monkeypatch, factory, token_log)

    client_a = HubSpotDataPullClient("hub_a")
    client_b = HubSpotDataPullClient("hub_b")
    await client_a.pull_crm_objects(object_types=["CONTACT"])
    await client_b.pull_crm_objects(object_types=["CONTACT"])

    _assert_tokens_never_cross(token_log)


# --- non-standard object families: each routed to its own adapter ---


@pytest.mark.asyncio
async def test_campaign_routes_to_marketing_campaigns_api():
    fake = _FakeAsyncClient(get_handlers={"/marketing/v3/campaigns": lambda params: _page([{"id": "cmp-1"}])})
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_crm_objects(client=fake, headers={}, object_types=["CAMPAIGN"])

    assert result["CAMPAIGN"] == [{"id": "cmp-1"}]


@pytest.mark.asyncio
async def test_landing_page_routes_to_cms_api():
    fake = _FakeAsyncClient(get_handlers={"/cms/v3/pages/landing-pages": lambda params: _page([{"id": "lp-1"}])})
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_crm_objects(client=fake, headers={}, object_types=["LANDING_PAGE"])

    assert result["LANDING_PAGE"] == [{"id": "lp-1"}]


@pytest.mark.asyncio
async def test_blog_post_routes_to_cms_api():
    fake = _FakeAsyncClient(get_handlers={"/cms/v3/blogs/posts": lambda params: _page([{"id": "bp-1"}])})
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_crm_objects(client=fake, headers={}, object_types=["BLOG_POST"])

    assert result["BLOG_POST"] == [{"id": "bp-1"}]


@pytest.mark.asyncio
async def test_object_list_routes_to_lists_search_as_a_read_despite_being_a_post():
    def search_handler(body):
        assert body == {"count": 100, "offset": 0}
        return _resp(200, {"lists": [{"listId": "l-1"}]})

    fake = _FakeAsyncClient(post_handlers={"/crm/v3/lists/search": search_handler})
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_crm_objects(client=fake, headers={}, object_types=["OBJECT_LIST"])

    assert result["OBJECT_LIST"] == [{"listId": "l-1"}]


@pytest.mark.asyncio
async def test_object_list_paginates_past_the_first_page():
    # Lists Search paginates via hasMore/offset in the response body, not
    # the standard paging.next.after cursor shape _paginate handles.
    # Previously _pull_lists made exactly one call and never looped,
    # silently dropping every list past the first 100.
    def search_handler(body):
        if body["offset"] == 0:
            return _resp(200, {"lists": [{"listId": "l-1"}], "hasMore": True, "offset": 100})
        assert body["offset"] == 100
        return _resp(200, {"lists": [{"listId": "l-2"}], "hasMore": False})

    fake = _FakeAsyncClient(post_handlers={"/crm/v3/lists/search": search_handler})
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_crm_objects(client=fake, headers={}, object_types=["OBJECT_LIST"])

    assert result["OBJECT_LIST"] == [{"listId": "l-1"}, {"listId": "l-2"}]


@pytest.mark.asyncio
async def test_object_list_treats_429_from_the_post_search_as_pull_failed():
    fake = _FakeAsyncClient(post_handlers={"/crm/v3/lists/search": lambda body: _resp(429, {})})
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_crm_objects(client=fake, headers={}, object_types=["OBJECT_LIST"])

    assert result["OBJECT_LIST"] == {"error": "pull_failed"}


# --- pull_object / list_read_only_tools: fixed capability dispatch ---


@pytest.mark.asyncio
async def test_list_read_only_tools_returns_the_fixed_capability_set():
    client = HubSpotDataPullClient("hub_a")
    tools = await client.list_read_only_tools()

    assert set(tools) == {
        "owners",
        "organization_details",
        "content_analytics",
        "marketing_email_analytics",
        "campaign_attribution",
    }


@pytest.mark.asyncio
async def test_pull_object_refuses_unrecognized_capability_name():
    client = HubSpotDataPullClient("hub_a")

    with pytest.raises(ReadOnlyViolation):
        await client.pull_object("create_contact")


@pytest.mark.asyncio
async def test_pull_object_degrades_to_pull_failed_instead_of_raising():
    # Previously pull_object had no except (try/finally only), so a real
    # HubSpot error here propagated uncaught — the one leaf pull method in
    # this file without the "never crash, just degrade" guarantee every
    # sibling method has. A caller that doesn't independently wrap this
    # call (gateway/debug_api.py's pull_capability route) got an
    # unhandled 500 instead of a graceful {"error": "pull_failed"}.
    fake = _FakeAsyncClient(get_handlers={"/crm/v3/owners/": lambda params: _resp(403, {})})
    client = HubSpotDataPullClient("hub_a")

    result = await client.pull_object("owners", client=fake, headers={})

    assert result == {"error": "pull_failed"}


@pytest.mark.asyncio
async def test_pull_object_owners_calls_the_owners_endpoint():
    fake = _FakeAsyncClient(get_handlers={"/crm/v3/owners/": lambda params: _page([{"id": "o-1"}])})
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_object("owners", client=fake, headers={})

    assert result == [{"id": "o-1"}]


@pytest.mark.asyncio
async def test_pull_object_organization_details_composes_three_endpoints():
    fake = _FakeAsyncClient(
        get_handlers={
            "/settings/v3/users/teams": lambda params: _resp(200, {"results": [{"id": "team-1"}]}),
            "/settings/v3/users/": lambda params: _resp(200, {"results": [{"id": "user-1"}]}),
            "/account-info/v3/details": lambda params: _resp(200, {"portalId": 123}),
        }
    )
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_object("organization_details", client=fake, headers={})

    assert result["teams"] == {"results": [{"id": "team-1"}]}
    assert result["users"] == {"results": [{"id": "user-1"}]}
    assert result["account"] == {"portalId": 123}


@pytest.mark.asyncio
async def test_pull_object_organization_details_degrades_per_endpoint_not_all_or_nothing():
    # Confirmed live that /settings/v3/users/teams needs its own scope
    # distinct from /settings/v3/users/ — a portal missing just that one
    # scope previously lost all three endpoints' data, not just the one
    # that actually failed.
    fake = _FakeAsyncClient(
        get_handlers={
            "/settings/v3/users/teams": lambda params: _resp(403, {}),
            "/settings/v3/users/": lambda params: _resp(200, {"results": [{"id": "user-1"}]}),
            "/account-info/v3/details": lambda params: _resp(200, {"portalId": 123}),
        }
    )
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_object("organization_details", client=fake, headers={})

    assert result["teams"] == {"error": "pull_failed"}
    assert result["users"] == {"results": [{"id": "user-1"}]}
    assert result["account"] == {"portalId": 123}


@pytest.mark.asyncio
async def test_pull_object_content_analytics_calls_analytics_endpoint():
    fake = _FakeAsyncClient(get_handlers={"/analytics/v2/reports/pages/total": lambda params: _resp(200, {"totals": {}})})
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_object("content_analytics", client=fake, headers={})

    assert result == {"totals": {}}


@pytest.mark.asyncio
async def test_pull_object_marketing_email_analytics_calls_statistics_endpoint():
    fake = _FakeAsyncClient(
        get_handlers={"/marketing/v3/emails/statistics/list": lambda params: _resp(200, {"totals": []})}
    )
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_object("marketing_email_analytics", client=fake, headers={})

    assert result == {"totals": []}


@pytest.mark.asyncio
async def test_pull_object_campaign_attribution_wraps_pull_campaign_data():
    fake = _FakeAsyncClient(
        get_handlers={
            "/marketing/v3/campaigns": lambda params: _page([{"id": "cmp-1"}]),
            "/marketing/v3/campaigns/cmp-1/reports/metrics": lambda params: _resp(200, {"revenue": 100}),
        }
    )
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_object("campaign_attribution", client=fake, headers={})

    assert result == {"campaigns": [{"id": "cmp-1", "revenue": 100}]}


# --- pull_campaign_data: enumerate then per-campaign metrics ---


@pytest.mark.asyncio
async def test_pull_campaign_data_enumerates_and_queries_each_campaign():
    seen_metric_calls = []

    def metrics_handler(campaign_id):
        def handler(params):
            seen_metric_calls.append(campaign_id)
            return _resp(200, {"revenue": 10})

        return handler

    fake = _FakeAsyncClient(
        get_handlers={
            "/marketing/v3/campaigns": lambda params: _page([{"id": "111"}, {"id": "222"}]),
            "/marketing/v3/campaigns/111/reports/metrics": metrics_handler("111"),
            "/marketing/v3/campaigns/222/reports/metrics": metrics_handler("222"),
        }
    )
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_campaign_data(client=fake, headers={})

    assert {record["id"] for record in result} == {"111", "222"}
    assert set(seen_metric_calls) == {"111", "222"}


@pytest.mark.asyncio
async def test_pull_campaign_data_returns_empty_when_campaign_list_fails():
    def failing_list_handler(params):
        raise RuntimeError("simulated CAMPAIGN access failure")

    fake = _FakeAsyncClient(get_handlers={"/marketing/v3/campaigns": failing_list_handler})
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_campaign_data(client=fake, headers={})

    assert result == []


@pytest.mark.asyncio
async def test_pull_campaign_data_one_campaigns_metrics_failure_does_not_fail_others():
    def metrics_handler(params):
        raise RuntimeError("simulated failure for this campaign only")

    fake = _FakeAsyncClient(
        get_handlers={
            "/marketing/v3/campaigns": lambda params: _page([{"id": "111"}, {"id": "222"}]),
            "/marketing/v3/campaigns/111/reports/metrics": metrics_handler,
            "/marketing/v3/campaigns/222/reports/metrics": lambda params: _resp(200, {"revenue": 5}),
        }
    )
    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_campaign_data(client=fake, headers={})

    by_id = {record["id"]: record for record in result}
    assert by_id["111"] == {"id": "111", "error": "pull_failed"}
    assert by_id["222"]["revenue"] == 5


# --- custom property discovery: /crm/v3/properties/{slug} ---


@pytest.mark.asyncio
async def test_discover_object_property_definitions_returns_name_and_hubspot_defined():
    fake = _FakeAsyncClient(
        get_handlers={
            "/crm/v3/properties/contacts": lambda params: _resp(
                200,
                {
                    "results": [
                        {"name": "email", "hubspotDefined": True},
                        {"name": "custom_lead_score", "hubspotDefined": False},
                    ]
                },
            )
        }
    )
    client = HubSpotDataPullClient("hub_a")
    definitions = await client.discover_object_property_definitions("CONTACT", client=fake, headers={})

    assert definitions == [
        {"name": "email", "hubspotDefined": True},
        {"name": "custom_lead_score", "hubspotDefined": False},
    ]


@pytest.mark.asyncio
async def test_discover_object_properties_returns_just_names():
    fake = _FakeAsyncClient(
        get_handlers={
            "/crm/v3/properties/contacts": lambda params: _resp(
                200, {"results": [{"name": "email", "hubspotDefined": True}]}
            )
        }
    )
    client = HubSpotDataPullClient("hub_a")
    names = await client.discover_object_properties("CONTACT", client=fake, headers={})

    assert names == ["email"]


@pytest.mark.asyncio
async def test_discover_object_property_definitions_filters_unsafe_names_defensively():
    fake = _FakeAsyncClient(
        get_handlers={
            "/crm/v3/properties/contacts": lambda params: _resp(
                200,
                {
                    "results": [
                        {"name": "email", "hubspotDefined": True},
                        {"name": "bad; name", "hubspotDefined": False},
                    ]
                },
            )
        }
    )
    client = HubSpotDataPullClient("hub_a")
    definitions = await client.discover_object_property_definitions("CONTACT", client=fake, headers={})

    assert [d["name"] for d in definitions] == ["email"]


@pytest.mark.asyncio
async def test_discover_object_property_definitions_returns_empty_for_non_standard_type():
    client = HubSpotDataPullClient("hub_a")
    definitions = await client.discover_object_property_definitions("CAMPAIGN")

    assert definitions == []


@pytest.mark.asyncio
async def test_discover_object_properties_only_uses_this_tenants_token(monkeypatch):
    token_log: dict[str, list[str]] = {}

    def factory(hub_id):
        return _FakeAsyncClient(
            get_handlers={"/crm/v3/properties/contacts": lambda params: _resp(200, {"results": []})}
        )

    _patch_client_for_hub(monkeypatch, factory, token_log)

    client_a = HubSpotDataPullClient("hub_a")
    client_b = HubSpotDataPullClient("hub_b")
    await client_a.discover_object_properties("CONTACT")
    await client_b.discover_object_properties("CONTACT")

    _assert_tokens_never_cross(token_log)


# --- pull_all: the scheduled job's full-snapshot entry point ---


@pytest.mark.asyncio
async def test_pull_all_produces_snapshot_of_generic_capabilities_crm_objects_and_campaign_data(monkeypatch):
    def factory(hub_id):
        get_handlers = {
            "/crm/v3/owners/": lambda params: _page([{"id": "o-1"}]),
            "/settings/v3/users/teams": lambda params: _resp(200, {}),
            "/settings/v3/users/": lambda params: _resp(200, {}),
            "/account-info/v3/details": lambda params: _resp(200, {}),
            "/analytics/v2/reports/pages/total": lambda params: _resp(200, {}),
            "/marketing/v3/emails/statistics/list": lambda params: _resp(200, {}),
            "/marketing/v3/campaigns": lambda params: _page([]),
            "/cms/v3/pages/landing-pages": lambda params: _page([]),
            "/cms/v3/blogs/posts": lambda params: _page([]),
        }
        post_handlers = {"/crm/v3/lists/search": lambda body: _resp(200, {"lists": []})}
        for slug in hubspot_client.CRM_OBJECT_REST_SLUGS.values():
            get_handlers[f"/crm/v3/objects/{slug}"] = lambda params: _page([])
        return _FakeAsyncClient(get_handlers=get_handlers, post_handlers=post_handlers)

    _patch_client_for_hub(monkeypatch, factory)

    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_all()

    assert result["owners"] == [{"id": "o-1"}]
    assert set(hubspot_client.CRM_OBJECT_TYPES) <= set(result.keys())
    assert "campaign_data" in result
    # campaign_attribution is excluded from pull_all()'s own generic loop —
    # it's just pull_campaign_data() wrapped, and "campaign_data" above
    # already covers that ground; see pull_all()'s own comment.
    assert "campaign_attribution" not in result


@pytest.mark.asyncio
async def test_pull_all_degrades_gracefully_when_token_fetch_fails(monkeypatch):
    async def fake_client_for_hub(self):
        raise RuntimeError("no vaulted token for this tenant")

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_all()

    assert result == {"error": "pull_failed"}


@pytest.mark.asyncio
async def test_pull_crm_objects_degrades_gracefully_when_token_fetch_fails(monkeypatch):
    # Previously only pull_all() wrapped its own _client_for_hub() call in
    # a try/except — pull_crm_objects (called directly by
    # gateway/debug_api.py's /crm/{object_type} route, not through
    # pull_all()) had no such guard and raised uncaught.
    async def fake_client_for_hub(self):
        raise RuntimeError("no vaulted token for this tenant")

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_crm_objects()

    assert result == {"error": "pull_failed"}


@pytest.mark.asyncio
async def test_pull_campaign_data_degrades_gracefully_when_token_fetch_fails(monkeypatch):
    async def fake_client_for_hub(self):
        raise RuntimeError("no vaulted token for this tenant")

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    client = HubSpotDataPullClient("hub_a")
    result = await client.pull_campaign_data()

    assert result == []


# --- constants: coverage discipline unchanged by the REST pivot ---


def test_crm_object_types_covers_segments_landing_pages_and_blog_posts():
    assert "OBJECT_LIST" in hubspot_client.CRM_OBJECT_TYPES
    assert "LANDING_PAGE" in hubspot_client.CRM_OBJECT_TYPES
    assert "BLOG_POST" in hubspot_client.CRM_OBJECT_TYPES


def test_crm_object_types_covers_campaign():
    assert "CAMPAIGN" in hubspot_client.CRM_OBJECT_TYPES


def test_every_standard_crm_object_type_has_a_rest_slug():
    # The four non-standard types (CAMPAIGN, LANDING_PAGE, BLOG_POST,
    # OBJECT_LIST) deliberately have no entry here — they route to their
    # own adapters instead of the generic /crm/v3/objects/ path.
    standard_types = set(hubspot_client.CRM_OBJECT_TYPES) - hubspot_client._NON_STANDARD_OBJECT_TYPES
    assert set(hubspot_client.CRM_OBJECT_REST_SLUGS.keys()) == standard_types


def test_object_type_categories_cover_every_crm_object_type_exactly_once():
    assert set(hubspot_client.OBJECT_TYPE_CATEGORIES.keys()) == set(hubspot_client.CRM_OBJECT_TYPES)
    valid_categories = {
        hubspot_client.CATEGORY_CRM_RECORDS,
        hubspot_client.CATEGORY_ENGAGEMENT_RECORDS,
        hubspot_client.CATEGORY_MARKETING_CONTENT,
        hubspot_client.CATEGORY_USERS,
    }
    assert set(hubspot_client.OBJECT_TYPE_CATEGORIES.values()) <= valid_categories


def test_crm_object_aliases_cover_every_object_type():
    assert set(hubspot_client.CRM_OBJECT_ALIASES.keys()) == set(hubspot_client.CRM_OBJECT_TYPES)
    for object_type, aliases in hubspot_client.CRM_OBJECT_ALIASES.items():
        assert aliases, f"{object_type} has no query aliases"


def test_crm_object_aliases_match_common_irregular_plurals():
    assert "companies" in hubspot_client.CRM_OBJECT_ALIASES["COMPANY"]
    assert "meetings" in hubspot_client.CRM_OBJECT_ALIASES["MEETING_EVENT"]
    assert "landing pages" in hubspot_client.CRM_OBJECT_ALIASES["LANDING_PAGE"]
    assert "blog posts" in hubspot_client.CRM_OBJECT_ALIASES["BLOG_POST"]


def test_category_generic_capabilities_only_names_real_capabilities():
    all_named = {name for names in hubspot_client.CATEGORY_GENERIC_CAPABILITIES.values() for name in names}
    assert all_named <= set(hubspot_client._GENERIC_CAPABILITIES.keys())


def test_is_safe_property_name_accepts_plain_identifiers():
    assert hubspot_client._is_safe_property_name("custom_deal_score") is True
    assert hubspot_client._is_safe_property_name("hs_object_id") is True


def test_is_safe_property_name_rejects_unsafe_characters():
    assert hubspot_client._is_safe_property_name("bad; DROP TABLE x") is False
    assert hubspot_client._is_safe_property_name("bad name") is False
    assert hubspot_client._is_safe_property_name("bad-name") is False
    assert hubspot_client._is_safe_property_name("1_leading_digit") is False


@pytest.mark.asyncio
async def test_rate_limited_paginate_raises_hubspot_rate_limited_directly():
    """_paginate itself, not wrapped by pull_crm_objects' own try/except —
    proves the 429 signal is real and distinguishable, not silently
    swallowed at the lowest layer (pull_crm_objects' own outer catch is
    what turns this into {"error": "pull_failed"} for callers, tested
    above)."""
    fake = _FakeAsyncClient(get_handlers={"/crm/v3/owners/": lambda params: _resp(429, {})})
    client = HubSpotDataPullClient("hub_a")

    with pytest.raises(HubSpotRateLimited):
        await client._paginate(fake, {}, "/crm/v3/owners/", {})


# --- custom objects (openspec/changes/custom-object-support): runtime-
# discovered objectTypeId, never a fixed CRM_OBJECT_REST_SLUGS-style lookup ---


def test_is_safe_object_type_id_accepts_the_real_shape():
    assert hubspot_client._is_safe_object_type_id("2-3465404") is True


def test_is_safe_object_type_id_rejects_unsafe_input():
    assert hubspot_client._is_safe_object_type_id("2-3465404; DROP TABLE x") is False
    assert hubspot_client._is_safe_object_type_id("not_an_id") is False
    assert hubspot_client._is_safe_object_type_id("") is False


@pytest.mark.asyncio
async def test_discover_custom_object_schemas_returns_real_schemas():
    fake = _FakeAsyncClient(
        get_handlers={
            "/crm-object-schemas/v3/schemas": lambda params: _resp(
                200,
                {
                    "results": [
                        {
                            "objectTypeId": "2-3465404",
                            "name": "transaction",
                            "labels": {"singular": "Transaction", "plural": "Transactions"},
                        }
                    ]
                },
            )
        }
    )
    client = HubSpotDataPullClient("hub_a")
    schemas = await client.discover_custom_object_schemas(client=fake, headers={})

    assert schemas == [
        {"objectTypeId": "2-3465404", "name": "transaction", "labels": {"singular": "Transaction", "plural": "Transactions"}}
    ]


@pytest.mark.asyncio
async def test_discover_custom_object_schemas_filters_unsafe_object_type_ids_defensively():
    fake = _FakeAsyncClient(
        get_handlers={
            "/crm-object-schemas/v3/schemas": lambda params: _resp(
                200,
                {
                    "results": [
                        {"objectTypeId": "2-3465404", "name": "transaction", "labels": {}},
                        {"objectTypeId": "bad; id", "name": "evil", "labels": {}},
                    ]
                },
            )
        }
    )
    client = HubSpotDataPullClient("hub_a")
    schemas = await client.discover_custom_object_schemas(client=fake, headers={})

    assert [s["objectTypeId"] for s in schemas] == ["2-3465404"]


@pytest.mark.asyncio
async def test_discover_custom_object_schemas_degrades_gracefully_without_custom_objects_access():
    fake = _FakeAsyncClient(get_handlers={"/crm-object-schemas/v3/schemas": lambda params: _resp(403, {})})
    client = HubSpotDataPullClient("hub_a")

    schemas = await client.discover_custom_object_schemas(client=fake, headers={})

    assert schemas == []


@pytest.mark.asyncio
async def test_discover_custom_object_schemas_only_uses_this_tenants_token(monkeypatch):
    token_log: dict[str, list[str]] = {}

    def factory(hub_id):
        return _FakeAsyncClient(get_handlers={"/crm-object-schemas/v3/schemas": lambda params: _page([])})

    _patch_client_for_hub(monkeypatch, factory, token_log)

    client_a = HubSpotDataPullClient("hub_a")
    client_b = HubSpotDataPullClient("hub_b")
    await client_a.discover_custom_object_schemas()
    await client_b.discover_custom_object_schemas()

    _assert_tokens_never_cross(token_log)


@pytest.mark.asyncio
async def test_pull_custom_object_returns_real_records():
    fake = _FakeAsyncClient(get_handlers={"/crm/v3/objects/2-3465404": lambda params: _page([{"id": "t-1"}])})
    client = HubSpotDataPullClient("hub_a")

    result = await client.pull_custom_object("2-3465404", client=fake, headers={})

    assert result == [{"id": "t-1"}]


@pytest.mark.asyncio
async def test_pull_custom_object_forwards_explicit_properties():
    seen_params = {}

    def handler(params):
        seen_params.update(params)
        return _page([])

    fake = _FakeAsyncClient(get_handlers={"/crm/v3/objects/2-3465404": handler})
    client = HubSpotDataPullClient("hub_a")

    await client.pull_custom_object("2-3465404", client=fake, headers={}, properties=["status", "amount"])

    assert seen_params["properties"] == "status,amount"


@pytest.mark.asyncio
async def test_pull_custom_object_rejects_unsafe_object_type_id_before_any_call():
    client = HubSpotDataPullClient("hub_a")

    result = await client.pull_custom_object("bad; id")

    assert result == {"error": "pull_failed"}


@pytest.mark.asyncio
async def test_pull_custom_object_degrades_gracefully_on_failure():
    def failing_handler(params):
        raise RuntimeError("simulated failure")

    fake = _FakeAsyncClient(get_handlers={"/crm/v3/objects/2-3465404": failing_handler})
    client = HubSpotDataPullClient("hub_a")

    result = await client.pull_custom_object("2-3465404", client=fake, headers={})

    assert result == {"error": "pull_failed"}


@pytest.mark.asyncio
async def test_pull_custom_object_only_uses_this_tenants_token(monkeypatch):
    token_log: dict[str, list[str]] = {}

    def factory(hub_id):
        return _FakeAsyncClient(get_handlers={"/crm/v3/objects/2-3465404": lambda params: _page([])})

    _patch_client_for_hub(monkeypatch, factory, token_log)

    client_a = HubSpotDataPullClient("hub_a")
    client_b = HubSpotDataPullClient("hub_b")
    await client_a.pull_custom_object("2-3465404")
    await client_b.pull_custom_object("2-3465404")

    _assert_tokens_never_cross(token_log)


@pytest.mark.asyncio
async def test_discover_custom_object_properties_returns_definitions():
    fake = _FakeAsyncClient(
        get_handlers={
            "/crm/v3/properties/2-3465404": lambda params: _resp(
                200, {"results": [{"name": "status", "hubspotDefined": False}]}
            )
        }
    )
    client = HubSpotDataPullClient("hub_a")

    definitions = await client.discover_custom_object_properties("2-3465404", client=fake, headers={})

    assert definitions == [{"name": "status", "hubspotDefined": False}]


@pytest.mark.asyncio
async def test_discover_custom_object_properties_rejects_unsafe_object_type_id():
    client = HubSpotDataPullClient("hub_a")

    definitions = await client.discover_custom_object_properties("bad; id")

    assert definitions == []
