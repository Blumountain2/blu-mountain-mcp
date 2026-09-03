"""Tests for debug_api.py: the API-key-gated plain HTTP surface for pulling
a real installed tenant's HubSpot data via Postman. Uses the same fake
httpx.AsyncClient pattern as tests/sync/test_hubspot_client.py, and
main.app directly (mirrors test_main.py's convention) so the real router
mounting/dependency wiring is under test, not a standalone app."""

import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import main
from config import settings
from db import get_pool
from sync.hubspot_client import HubSpotDataPullClient


def _resp(status_code: int, body: dict) -> httpx.Response:
    request = httpx.Request("GET", "https://api.hubapi.com/fake")
    return httpx.Response(status_code, json=body, request=request)


def _page(results: list[dict]) -> httpx.Response:
    return _resp(200, {"results": results, "paging": {}})


class _FakeAsyncClient:
    def __init__(self, get_handlers: dict | None = None, post_handlers: dict | None = None):
        self._get_handlers = get_handlers or {}
        self._post_handlers = post_handlers or {}

    def _path(self, url: str) -> str:
        return url.replace("https://api.hubapi.com", "")

    async def get(self, url, headers=None, params=None):
        handler = self._get_handlers.get(self._path(url))
        if handler is None:
            raise AssertionError(f"no fake GET handler registered for {self._path(url)}")
        return handler(params or {})

    async def post(self, url, headers=None, json=None):
        handler = self._post_handlers.get(self._path(url))
        if handler is None:
            raise AssertionError(f"no fake POST handler registered for {self._path(url)}")
        return handler(json or {})

    async def aclose(self):
        pass


async def _seed_tenant(hub_id: str):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO tenants (hub_id, install_status) VALUES ($1, 'installed')", hub_id
    )


async def _client():
    return AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test")


@pytest.mark.asyncio
async def test_missing_api_key_rejected():
    async with await _client() as client:
        response = await client.get("/debug/hubspot/tenants")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wrong_api_key_rejected():
    async with await _client() as client:
        response = await client.get("/debug/hubspot/tenants", headers={"X-Debug-Api-Key": "wrong"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_empty_configured_key_fails_closed(monkeypatch):
    """An unset DEBUG_API_KEY must reject every request, including one
    that (mistakenly) sends an empty header value to match — fail closed,
    the same posture as an empty FASTMCP_ALLOWED_GOOGLE_DOMAINS."""
    monkeypatch.setattr(settings, "debug_api_key", "")
    async with await _client() as client:
        response = await client.get("/debug/hubspot/tenants", headers={"X-Debug-Api-Key": ""})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_tenants_returns_installed_tenants_with_names():
    await _seed_tenant("hub_debug_a")
    pool = await get_pool()
    await pool.execute(
        "UPDATE tenants SET portal_name = $1 WHERE hub_id = $2", "Debug Test Co", "hub_debug_a"
    )

    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/tenants", headers={"X-Debug-Api-Key": settings.debug_api_key}
        )

    assert response.status_code == 200
    by_id = {t["hub_id"]: t["name"] for t in response.json()}
    assert by_id["hub_debug_a"] == "Debug Test Co"


@pytest.mark.asyncio
async def test_list_object_types_returns_crm_types_and_capabilities():
    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/object-types", headers={"X-Debug-Api-Key": settings.debug_api_key}
        )

    assert response.status_code == 200
    body = response.json()
    assert "CONTACT" in body["crm_object_types"]
    assert "owners" in body["capabilities"]


@pytest.mark.asyncio
async def test_crm_pull_rejects_unknown_hub_id():
    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/hub_never_installed/crm/contacts",
            headers={"X-Debug-Api-Key": settings.debug_api_key},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_crm_pull_rejects_unknown_object_type():
    await _seed_tenant("hub_debug_bad_type")
    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/hub_debug_bad_type/crm/not_a_real_type",
            headers={"X-Debug-Api-Key": settings.debug_api_key},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_crm_pull_returns_real_data_and_audits(monkeypatch):
    await _seed_tenant("hub_debug_pull")

    async def fake_client_for_hub(self):
        fake = _FakeAsyncClient(get_handlers={"/crm/v3/objects/contacts": lambda params: _page([{"id": "1"}])})
        return fake, {"Authorization": "Bearer fake"}

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/hub_debug_pull/crm/contacts", headers={"X-Debug-Api-Key": settings.debug_api_key}
        )

    assert response.status_code == 200
    assert response.json() == {"CONTACT": [{"id": "1"}]}

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT event_type, detail FROM audit_log WHERE hub_id = $1 AND event_type = 'debug_api_pull'",
        "hub_debug_pull",
    )
    assert row is not None
    assert json.loads(row["detail"])["object_type"] == "CONTACT"


@pytest.mark.asyncio
async def test_crm_pull_forwards_explicit_properties(monkeypatch):
    await _seed_tenant("hub_debug_props")
    seen_params = {}

    async def fake_client_for_hub(self):
        def handler(params):
            seen_params.update(params)
            return _page([])

        return _FakeAsyncClient(get_handlers={"/crm/v3/objects/contacts": handler}), {"Authorization": "Bearer fake"}

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/hub_debug_props/crm/contacts",
            params={"properties": "email,jobtitle"},
            headers={"X-Debug-Api-Key": settings.debug_api_key},
        )

    assert response.status_code == 200
    assert seen_params["properties"] == "email,jobtitle"


@pytest.mark.asyncio
async def test_properties_endpoint_returns_definitions(monkeypatch):
    await _seed_tenant("hub_debug_property_defs")

    async def fake_client_for_hub(self):
        fake = _FakeAsyncClient(
            get_handlers={
                "/crm/v3/properties/contacts": lambda params: _resp(
                    200, {"results": [{"name": "email", "hubspotDefined": True}]}
                )
            }
        )
        return fake, {"Authorization": "Bearer fake"}

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/hub_debug_property_defs/properties/contacts",
            headers={"X-Debug-Api-Key": settings.debug_api_key},
        )

    assert response.status_code == 200
    assert response.json()["properties"] == [{"name": "email", "hubspotDefined": True}]


@pytest.mark.asyncio
async def test_capability_endpoint_rejects_unrecognized_name():
    await _seed_tenant("hub_debug_bad_capability")
    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/hub_debug_bad_capability/capability/not_a_real_capability",
            headers={"X-Debug-Api-Key": settings.debug_api_key},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_capability_endpoint_returns_real_data(monkeypatch):
    await _seed_tenant("hub_debug_owners")

    async def fake_client_for_hub(self):
        fake = _FakeAsyncClient(get_handlers={"/crm/v3/owners/": lambda params: _page([{"id": "o-1"}])})
        return fake, {"Authorization": "Bearer fake"}

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/hub_debug_owners/capability/owners",
            headers={"X-Debug-Api-Key": settings.debug_api_key},
        )

    assert response.status_code == 200
    assert response.json() == {"owners": [{"id": "o-1"}]}


@pytest.mark.asyncio
async def test_never_constructs_a_client_for_a_different_tenant(monkeypatch):
    """Isolation: proves the debug API only ever constructs
    HubSpotDataPullClient for the hub_id in the URL path, never any other
    tenant — the concrete thing "no leakage" means, not just an inference
    from a status code."""
    await _seed_tenant("hub_debug_leak_target")
    await _seed_tenant("hub_debug_other")

    constructed_hub_ids = []
    real_init = HubSpotDataPullClient.__init__

    def _recording_init(self, hub_id):
        constructed_hub_ids.append(hub_id)
        real_init(self, hub_id)

    monkeypatch.setattr(HubSpotDataPullClient, "__init__", _recording_init)

    async def fake_client_for_hub(self):
        return _FakeAsyncClient(get_handlers={"/crm/v3/owners/": lambda params: _page([])}), {
            "Authorization": "Bearer fake"
        }

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    async with await _client() as client:
        await client.get(
            "/debug/hubspot/hub_debug_leak_target/capability/owners",
            headers={"X-Debug-Api-Key": settings.debug_api_key},
        )

    assert constructed_hub_ids == ["hub_debug_leak_target"]
    assert "hub_debug_other" not in constructed_hub_ids


@pytest.mark.asyncio
async def test_campaigns_endpoint_returns_real_data(monkeypatch):
    await _seed_tenant("hub_debug_campaigns")

    async def fake_client_for_hub(self):
        fake = _FakeAsyncClient(
            get_handlers={
                "/marketing/v3/campaigns": lambda params: _page([{"id": "cmp-1"}]),
                "/marketing/v3/campaigns/cmp-1/reports/metrics": lambda params: _resp(200, {"revenue": 5}),
            }
        )
        return fake, {"Authorization": "Bearer fake"}

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/hub_debug_campaigns/campaigns", headers={"X-Debug-Api-Key": settings.debug_api_key}
        )

    assert response.status_code == 200
    assert response.json() == {"campaigns": [{"id": "cmp-1", "revenue": 5}]}


@pytest.mark.asyncio
async def test_custom_objects_endpoint_returns_real_schemas(monkeypatch):
    await _seed_tenant("hub_debug_custom_schemas")

    async def fake_client_for_hub(self):
        fake = _FakeAsyncClient(
            get_handlers={
                "/crm-object-schemas/v3/schemas": lambda params: _resp(
                    200, {"results": [{"objectTypeId": "2-3465404", "name": "transaction", "labels": {}}]}
                )
            }
        )
        return fake, {"Authorization": "Bearer fake"}

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/hub_debug_custom_schemas/custom-objects",
            headers={"X-Debug-Api-Key": settings.debug_api_key},
        )

    assert response.status_code == 200
    assert response.json()["custom_object_schemas"] == [{"objectTypeId": "2-3465404", "name": "transaction", "labels": {}}]


@pytest.mark.asyncio
async def test_custom_objects_endpoint_rejects_unknown_hub_id():
    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/hub_never_installed/custom-objects",
            headers={"X-Debug-Api-Key": settings.debug_api_key},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_custom_object_records_endpoint_returns_real_data(monkeypatch):
    await _seed_tenant("hub_debug_custom_pull")

    async def fake_client_for_hub(self):
        fake = _FakeAsyncClient(get_handlers={"/crm/v3/objects/2-3465404": lambda params: _page([{"id": "t-1"}])})
        return fake, {"Authorization": "Bearer fake"}

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/hub_debug_custom_pull/custom-objects/2-3465404",
            headers={"X-Debug-Api-Key": settings.debug_api_key},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["object_type_id"] == "2-3465404"
    assert body["records"] == [{"id": "t-1"}]


@pytest.mark.asyncio
async def test_custom_object_records_endpoint_forwards_properties(monkeypatch):
    await _seed_tenant("hub_debug_custom_props")
    seen_params = {}

    async def fake_client_for_hub(self):
        def handler(params):
            seen_params.update(params)
            return _page([])

        return _FakeAsyncClient(get_handlers={"/crm/v3/objects/2-3465404": handler}), {"Authorization": "Bearer fake"}

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    async with await _client() as client:
        response = await client.get(
            "/debug/hubspot/hub_debug_custom_props/custom-objects/2-3465404",
            params={"properties": "status,amount"},
            headers={"X-Debug-Api-Key": settings.debug_api_key},
        )

    assert response.status_code == 200
    assert seen_params["properties"] == "status,amount"


@pytest.mark.asyncio
async def test_custom_objects_never_constructs_a_client_for_a_different_tenant(monkeypatch):
    await _seed_tenant("hub_debug_custom_leak_target")
    await _seed_tenant("hub_debug_custom_other")

    constructed_hub_ids = []
    real_init = HubSpotDataPullClient.__init__

    def _recording_init(self, hub_id):
        constructed_hub_ids.append(hub_id)
        real_init(self, hub_id)

    monkeypatch.setattr(HubSpotDataPullClient, "__init__", _recording_init)

    async def fake_client_for_hub(self):
        return _FakeAsyncClient(get_handlers={"/crm-object-schemas/v3/schemas": lambda params: _page([])}), {
            "Authorization": "Bearer fake"
        }

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)

    async with await _client() as client:
        await client.get(
            "/debug/hubspot/hub_debug_custom_leak_target/custom-objects",
            headers={"X-Debug-Api-Key": settings.debug_api_key},
        )

    assert constructed_hub_ids == ["hub_debug_custom_leak_target"]
    assert "hub_debug_custom_other" not in constructed_hub_ids
