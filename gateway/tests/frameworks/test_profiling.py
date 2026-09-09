"""Task 2 tests (specs/tenant-field-profiling/spec.md): profiling reads
only through the existing, already-allowlisted REST pull path
(HubSpotDataPullClient.pull_crm_objects/discover_object_property_definitions
— see openspec/changes/hubspot-rest-api-pivot), is scoped to exactly one
tenant's own connection, correctly distinguishes a populated field from an
unpopulated one, and is informed by — but doesn't require — a known
vertical's framework guidance."""

import httpx
import pytest

from frameworks import guidance
from frameworks.profiling import FieldProfile, _profile_object_type, profile_tenant_fields
from sync.hubspot_client import CRM_OBJECT_REST_SLUGS, HubSpotDataPullClient


def _resp(status_code: int, body: dict) -> httpx.Response:
    request = httpx.Request("GET", "https://api.hubapi.com/fake")
    return httpx.Response(status_code, json=body, request=request)


def _page(results: list[dict]) -> httpx.Response:
    return _resp(200, {"results": results, "paging": {}})


class _FakeAsyncClient:
    """Same shape as tests/sync/test_hubspot_client.py's own fake: returns
    the same canned records for every standard object type's
    /crm/v3/objects/{slug} GET, regardless of which type was requested —
    enough to prove profiling's own logic without re-testing
    pull_crm_objects's per-type dispatch (already covered there). Answers
    /crm/v3/properties/{slug} with no property definitions by default —
    enough for tests that assert on record-derived properties, not
    discovered ones."""

    def __init__(self, records: list[dict], property_definitions: list[dict] | None = None):
        self._records = records
        self._property_definitions = property_definitions or []

    async def get(self, url, headers=None, params=None):
        if "/crm/v3/properties/" in url:
            return _resp(200, {"results": self._property_definitions})
        return _page(self._records)

    async def aclose(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def _patch_client(monkeypatch, records, property_definitions=None):
    async def fake_client_for_hub(self):
        return _FakeAsyncClient(records, property_definitions), {"Authorization": f"Bearer access-token-for-{self.hub_id}"}

    monkeypatch.setattr(HubSpotDataPullClient, "_client_for_hub", fake_client_for_hub)


# --- pure logic, no HubSpot mocking needed ---


def test_profile_object_type_distinguishes_populated_from_unpopulated():
    records = [
        {"properties": {"name": "Acme", "custom_stale_field": None}},
        {"properties": {"name": "Beta", "custom_stale_field": ""}},
    ]

    profiles = {p.name: p for p in _profile_object_type(records, guidance=None, custom_by_name={})}

    assert profiles["name"].populated is True
    assert profiles["name"].populated_count == 2
    assert profiles["custom_stale_field"].populated is False
    assert profiles["custom_stale_field"].populated_count == 0


def test_profile_object_type_records_total_and_partial_population():
    records = [
        {"properties": {"sometimes_set": "value"}},
        {"properties": {"sometimes_set": None}},
        {"properties": {"sometimes_set": None}},
    ]

    profiles = {p.name: p for p in _profile_object_type(records, guidance=None, custom_by_name={})}

    assert profiles["sometimes_set"].populated is True
    assert profiles["sometimes_set"].populated_count == 1
    assert profiles["sometimes_set"].total_records == 3


def test_profile_object_type_applies_framework_guidance():
    records = [{"properties": {"lifecyclestage": "lead", "hs_object_id": "1"}}]
    guidance = {"trust_by_default": ["hs_object_id"], "unreliable_by_default": ["lifecyclestage"]}

    profiles = {p.name: p for p in _profile_object_type(records, guidance, custom_by_name={})}

    assert profiles["hs_object_id"].framework_guidance == "trust_by_default"
    assert profiles["lifecyclestage"].framework_guidance == "unreliable_by_default"


def test_profile_object_type_unmentioned_property_has_no_guidance():
    records = [{"properties": {"some_other_field": "x"}}]
    guidance = {"trust_by_default": ["hs_object_id"], "unreliable_by_default": ["lifecyclestage"]}

    profiles = {p.name: p for p in _profile_object_type(records, guidance, custom_by_name={})}

    assert profiles["some_other_field"].framework_guidance is None


# --- full profile_tenant_fields, through the real pull layer (faked transport) ---


@pytest.mark.asyncio
async def test_profile_tenant_fields_runs_without_a_known_vertical(monkeypatch):
    _patch_client(monkeypatch, [{"properties": {"name": "Acme"}}])

    result = await profile_tenant_fields("hub_a", object_types=["COMPANY"])

    assert result["COMPANY"][0].name == "name"
    assert result["COMPANY"][0].framework_guidance is None


@pytest.mark.asyncio
async def test_profile_tenant_fields_uses_known_vertical_guidance(monkeypatch):
    _patch_client(monkeypatch, [{"properties": {"lifecyclestage": "lead"}}])
    monkeypatch.setitem(
        guidance.FRAMEWORK_PROPERTY_GUIDANCE,
        "saas",
        {"trust_by_default": [], "unreliable_by_default": ["lifecyclestage"]},
    )

    result = await profile_tenant_fields("hub_a", object_types=["COMPANY"], vertical="saas")

    assert result["COMPANY"][0].framework_guidance == "unreliable_by_default"


@pytest.mark.asyncio
async def test_profile_tenant_fields_skips_object_types_that_failed_to_pull(monkeypatch):
    async def fake_pull_crm_objects(self, client=None, object_types=None, properties=None, headers=None):
        return {"COMPANY": [{"properties": {"name": "Acme"}}], "DEAL": {"error": "pull_failed"}}

    monkeypatch.setattr(HubSpotDataPullClient, "pull_crm_objects", fake_pull_crm_objects)
    _patch_client(monkeypatch, [])  # backs discover_object_property_definitions's own connection

    result = await profile_tenant_fields("hub_a", object_types=["COMPANY", "DEAL"])

    assert "COMPANY" in result
    assert "DEAL" not in result


@pytest.mark.asyncio
async def test_profile_tenant_fields_only_ever_constructs_client_for_the_requested_tenant(monkeypatch):
    """Isolation: proves the actual HubSpot-pulling client is only ever
    constructed for the one tenant being profiled — not an inference from
    a raised exception, the concrete construction itself."""
    constructed_hub_ids = []
    real_init = HubSpotDataPullClient.__init__

    def _recording_init(self, hub_id):
        constructed_hub_ids.append(hub_id)
        real_init(self, hub_id)

    monkeypatch.setattr(HubSpotDataPullClient, "__init__", _recording_init)
    _patch_client(monkeypatch, [{"properties": {"name": "Acme"}}])

    await profile_tenant_fields("hub_only_this_one", object_types=["COMPANY"])

    assert constructed_hub_ids == ["hub_only_this_one"]


@pytest.mark.asyncio
async def test_profile_tenant_fields_only_calls_allowlisted_pull_methods(monkeypatch):
    """Proves profiling never bypasses the allowlisted pull path: the only
    HubSpotDataPullClient methods it calls are discover_object_property_definitions
    (task 3.4 — custom-field discovery via REST's /crm/v3/properties/{slug},
    itself just an allowlisted GET) and pull_crm_objects, both already
    proven elsewhere to only ever call HubSpot's own hand-enumerated,
    read-only REST endpoints."""
    calls = []
    real_pull = HubSpotDataPullClient.pull_crm_objects
    real_discover = HubSpotDataPullClient.discover_object_property_definitions

    async def _recording_pull(self, client=None, object_types=None, properties=None, headers=None):
        calls.append("pull_crm_objects")
        return await real_pull(self, client=client, object_types=object_types, properties=properties, headers=headers)

    async def _recording_discover(self, object_type, client=None, headers=None):
        calls.append("discover_object_property_definitions")
        return await real_discover(self, object_type, client=client, headers=headers)

    monkeypatch.setattr(HubSpotDataPullClient, "pull_crm_objects", _recording_pull)
    monkeypatch.setattr(HubSpotDataPullClient, "discover_object_property_definitions", _recording_discover)
    _patch_client(monkeypatch, [{"properties": {"name": "Acme"}}])

    await profile_tenant_fields("hub_a", object_types=["COMPANY"])

    assert set(calls) == {"pull_crm_objects", "discover_object_property_definitions"}


# --- standard-vs-custom distinction (task 3.4): now sourced from REST's
# own authoritative hubspotDefined flag, not a name-based heuristic ---


def test_profile_object_type_marks_a_property_custom_when_hubspot_defined_is_false():
    records = [{"properties": {"gumpper_lead_score": "42"}}]

    profiles = {
        p.name: p
        for p in _profile_object_type(records, guidance=None, custom_by_name={"gumpper_lead_score": True})
    }

    assert profiles["gumpper_lead_score"].is_custom is True


def test_profile_object_type_does_not_mark_a_property_custom_when_hubspot_defined_is_true():
    records = [{"properties": {"email": "a@example.com", "hs_object_id": "1"}}]

    profiles = {
        p.name: p
        for p in _profile_object_type(
            records, guidance=None, custom_by_name={"email": False, "hs_object_id": False}
        )
    }

    assert profiles["email"].is_custom is False
    assert profiles["hs_object_id"].is_custom is False


def test_profile_object_type_defaults_to_not_custom_when_no_definition_was_discovered():
    # A property present on a record but absent from the discovered
    # property-definitions list (edge case: HubSpot returned it on the
    # record but not in the properties endpoint's response) shouldn't be
    # guessed at — defaults to not-custom rather than reintroducing a
    # heuristic.
    records = [{"properties": {"undiscovered_field": "x"}}]

    profiles = {p.name: p for p in _profile_object_type(records, guidance=None, custom_by_name={})}

    assert profiles["undiscovered_field"].is_custom is False


@pytest.mark.asyncio
async def test_profile_tenant_fields_marks_custom_fields_using_hubspot_defined_flag(monkeypatch):
    _patch_client(
        monkeypatch,
        [{"properties": {"email": "a@example.com", "gumpper_lead_score": "42"}}],
        property_definitions=[
            {"name": "email", "hubspotDefined": True},
            {"name": "gumpper_lead_score", "hubspotDefined": False},
        ],
    )

    result = await profile_tenant_fields("hub_a", object_types=["CONTACT"])

    by_name = {p.name: p for p in result["CONTACT"]}
    assert by_name["email"].is_custom is False
    assert by_name["gumpper_lead_score"].is_custom is True


# --- custom objects (2026-09-08): profiled the same way as a standard
# object type, just keyed by objectTypeId and reached via the
# discover_custom_object_properties/pull_custom_object pair ---


@pytest.mark.asyncio
async def test_profile_tenant_fields_also_profiles_custom_object_type_ids(monkeypatch):
    _patch_client(monkeypatch, [{"properties": {"amount": "100"}}])

    result = await profile_tenant_fields(
        "hub_a", object_types=["COMPANY"], custom_object_type_ids=["2-123456"]
    )

    assert "COMPANY" in result
    assert "2-123456" in result
    assert result["2-123456"][0].name == "amount"


@pytest.mark.asyncio
async def test_profile_tenant_fields_marks_custom_object_fields_using_hubspot_defined_flag(monkeypatch):
    _patch_client(
        monkeypatch,
        [{"properties": {"transaction_status": "closed"}}],
        property_definitions=[{"name": "transaction_status", "hubspotDefined": False}],
    )

    result = await profile_tenant_fields("hub_a", object_types=[], custom_object_type_ids=["2-123456"])

    by_name = {p.name: p for p in result["2-123456"]}
    assert by_name["transaction_status"].is_custom is True


@pytest.mark.asyncio
async def test_profile_tenant_fields_omitting_custom_object_type_ids_only_profiles_standard_types(monkeypatch):
    _patch_client(monkeypatch, [{"properties": {"name": "Acme"}}])

    result = await profile_tenant_fields("hub_a", object_types=["COMPANY"])

    assert set(result.keys()) == {"COMPANY"}


@pytest.mark.asyncio
async def test_a_discovery_failure_for_one_object_type_does_not_fail_the_whole_run(monkeypatch):
    async def fake_discover(self, object_type, client=None, headers=None):
        raise RuntimeError("simulated properties endpoint failure")

    monkeypatch.setattr(HubSpotDataPullClient, "discover_object_property_definitions", fake_discover)
    _patch_client(monkeypatch, [{"properties": {"name": "Acme"}}])

    # Degrades to the default pull for COMPANY rather than raising.
    result = await profile_tenant_fields("hub_a", object_types=["COMPANY"])

    assert result["COMPANY"][0].name == "name"
