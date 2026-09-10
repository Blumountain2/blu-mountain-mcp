"""Tasks 4.5/4.6/8.3/SC-10: proves Airtable staging tags every record by
client and never lets one tenant's pull write into another tenant's rows,
using a fake Airtable API so no real base is touched."""

from unittest.mock import AsyncMock

import pytest

from db import get_pool
from sync import airtable_staging
from sync.airtable_staging import (
    normalize_diagnostic_report,
    normalize_record,
    run_staging_cycle,
    stage_diagnostic_report,
    stage_tenant_pull,
)


class _FakeTableSchema:
    def __init__(self, name):
        self.name = name


class _FakeBaseSchema:
    def __init__(self, tables):
        self.tables = tables


class _FakeTable:
    def __init__(self, store, name):
        self._store = store
        self._name = name

    def batch_create(self, rows):
        self._store.setdefault(self._name, []).extend(rows)

    def create(self, row):
        self._store.setdefault(self._name, []).append(row)


class _FakeBase:
    def __init__(self):
        self.tables_created = []
        self._existing = set()
        self.written = {}

    def schema(self):
        return _FakeBaseSchema([_FakeTableSchema(n) for n in self._existing])

    def create_table(self, name, fields):
        self.tables_created.append(name)
        self._existing.add(name)

    def table(self, name):
        return _FakeTable(self.written, name)


class _FakeApi:
    def __init__(self, base):
        self._base = base

    def base(self, base_id):
        return self._base


@pytest.fixture
def fake_base(monkeypatch):
    base = _FakeBase()
    monkeypatch.setattr(airtable_staging, "_api", lambda: _FakeApi(base))
    return base


def test_normalize_record_tags_by_client():
    row = normalize_record("hub_a", "list_contacts", {"id": "contact-1", "email": "a@x.com"})
    assert row["Client"] == "hub_a"
    assert row["Source ID"] == "contact-1"
    assert "contact-1" in row["Data"]


def test_normalize_record_reads_hs_object_id_from_properties():
    # query_crm_data's real CRM object shape (COMPANY, DEAL, confirmed
    # live) has no top-level "id" at all, only properties.hs_object_id —
    # sync.hubspot_client.pull_crm_objects selects it explicitly.
    row = normalize_record(
        "hub_a", "COMPANY", {"objectTypeId": "0-2", "properties": {"hs_object_id": "443702868207", "name": "Acme"}}
    )
    assert row["Source ID"] == "443702868207"


def test_normalize_record_prefers_hs_object_id_over_top_level_id():
    row = normalize_record(
        "hub_a", "COMPANY", {"id": "wrong", "properties": {"hs_object_id": "right"}}
    )
    assert row["Source ID"] == "right"


def test_normalize_record_falls_back_to_top_level_id_when_no_properties():
    # The generic per-object tools (e.g. get_organization_details) and
    # campaign_data's per-campaign records use a top-level "id" instead of
    # a properties dict — confirmed separately during this project's
    # earlier live testing.
    row = normalize_record("hub_a", "get_organization_details", {"id": "team-1", "name": "Sales"})
    assert row["Source ID"] == "team-1"


def test_ensure_schema_creates_only_missing_tables(fake_base):
    fake_base._existing.add("Contacts")
    airtable_staging.ensure_schema()

    assert "Contacts" not in fake_base.tables_created
    assert "Deals" in fake_base.tables_created
    assert "SybillTranscripts" in fake_base.tables_created
    assert "DiagnosticReports" in fake_base.tables_created


def test_ensure_schema_skips_diagnostic_reports_table_if_already_present(fake_base):
    fake_base._existing.add("DiagnosticReports")
    airtable_staging.ensure_schema()

    assert "DiagnosticReports" not in fake_base.tables_created


def test_normalize_diagnostic_report_tags_by_client_and_vertical():
    report = {"summary": "Healthy.", "kpis": [{"name": "MRR", "value": "$1,000"}], "risk_flags": ["none"]}
    row = normalize_diagnostic_report("hub_a", "saas", report)

    assert row["Client"] == "hub_a"
    assert row["Vertical"] == "saas"
    assert row["Summary"] == "Healthy."
    assert "MRR" in row["KPIs"]
    assert "none" in row["Risk Flags"]


@pytest.mark.asyncio
async def test_stage_diagnostic_report_writes_one_row_to_the_diagnostic_reports_table(fake_base):
    report = {"summary": "Healthy.", "kpis": [], "risk_flags": []}
    await stage_diagnostic_report("hub_a", "saas", report)

    rows = fake_base.written["DiagnosticReports"]
    assert len(rows) == 1
    assert rows[0]["Client"] == "hub_a"
    assert rows[0]["Vertical"] == "saas"


@pytest.mark.asyncio
async def test_stage_diagnostic_report_isolation_across_tenants(fake_base):
    await stage_diagnostic_report("hub_a", "saas", {"summary": "a", "kpis": [], "risk_flags": []})
    await stage_diagnostic_report("hub_b", "marketplace", {"summary": "b", "kpis": [], "risk_flags": []})

    rows = fake_base.written["DiagnosticReports"]
    by_client = {r["Client"]: r for r in rows}
    assert by_client["hub_a"]["Summary"] == "a"
    assert by_client["hub_b"]["Summary"] == "b"


@pytest.mark.asyncio
async def test_stage_tenant_pull_tags_every_row_with_correct_client(fake_base):
    pulled = {
        "list_contacts": [{"id": "contact-1"}, {"id": "contact-2"}],
        "list_deals": {"id": "deal-1"},
    }
    await stage_tenant_pull("hub_a", pulled)

    assert all(row["Client"] == "hub_a" for row in fake_base.written["Contacts"])
    assert all(row["Client"] == "hub_a" for row in fake_base.written["Deals"])


@pytest.mark.asyncio
async def test_stage_tenant_pull_isolation_across_tenants(fake_base):
    await stage_tenant_pull("hub_a", {"list_companies": {"id": "shared-looking-id"}})
    await stage_tenant_pull("hub_b", {"list_companies": {"id": "shared-looking-id"}})

    rows = fake_base.written["Companies"]
    hub_a_rows = [r for r in rows if r["Client"] == "hub_a"]
    hub_b_rows = [r for r in rows if r["Client"] == "hub_b"]

    assert len(hub_a_rows) == 1
    assert len(hub_b_rows) == 1
    # Same underlying HubSpot-looking ID for two tenants never merges into
    # one row or gets attributed to the wrong tenant.
    assert hub_a_rows[0] is not hub_b_rows[0]


@pytest.mark.asyncio
async def test_stage_tenant_pull_skips_errored_results(fake_base):
    await stage_tenant_pull("hub_a", {"list_contacts": {"error": "pull_failed"}})
    assert "Contacts" not in fake_base.written


@pytest.mark.asyncio
async def test_stage_tenant_pull_stages_organization_landing_page_and_blog_post(fake_base):
    # These three previously had no matching OBJECT_TABLES keyword and were
    # pulled from HubSpot successfully, then silently dropped before ever
    # reaching Airtable.
    pulled = {
        "get_organization_details": {"id": "team-1", "name": "Sales"},
        "LANDING_PAGE": [{"id": "lp-1"}],
        "BLOG_POST": [{"id": "bp-1"}],
    }
    await stage_tenant_pull("hub_a", pulled)

    assert fake_base.written["Teams"][0]["Source ID"] == "team-1"
    assert fake_base.written["LandingPages"][0]["Source ID"] == "lp-1"
    assert fake_base.written["BlogPosts"][0]["Source ID"] == "bp-1"


@pytest.mark.asyncio
async def test_stage_tenant_pull_stages_quote_records(fake_base):
    # QUOTE (added to CRM_OBJECT_TYPES 2026-09-02) previously had no
    # matching OBJECT_TABLES keyword either, the same silent-drop failure
    # mode as the organization/LANDING_PAGE/BLOG_POST case above.
    pulled = {"QUOTE": [{"properties": {"hs_object_id": "q-1"}}]}
    await stage_tenant_pull("hub_a", pulled)

    assert fake_base.written["Quotes"][0]["Source ID"] == "q-1"


@pytest.mark.asyncio
async def test_marketing_email_analytics_does_not_collide_with_real_email_records(fake_base):
    # "email" is a substring of "marketing_email_analytics", so the
    # generic capability's one portal-wide stats dict previously landed in
    # the same "Emails" table as real per-engagement EMAIL CRM records —
    # two structurally unrelated row shapes sharing one table.
    pulled = {
        "EMAIL": [{"properties": {"hs_object_id": "e-1"}}],
        "marketing_email_analytics": {"id": "stats-1"},
    }
    await stage_tenant_pull("hub_a", pulled)

    assert [r["Source ID"] for r in fake_base.written["Emails"]] == ["e-1"]
    assert fake_base.written["MarketingEmailAnalytics"][0]["Source ID"] == "stats-1"


@pytest.mark.asyncio
async def test_stage_tenant_pull_stages_campaign_data_list_as_one_row_per_campaign(fake_base):
    # pull_campaign_data() returns a list of per-campaign records (each
    # carrying its own "id"), the same shape as every other object type —
    # not a dict keyed by campaign ID, which would collapse every
    # campaign's metrics into a single malformed row. Staged into its own
    # CampaignMetrics table, not "Campaigns" — pull_crm_objects()'s
    # "CAMPAIGN" key (plain CRM records) and this "campaign_data" key
    # (engagement metrics) are structurally different row shapes and must
    # not collide under the same Source ID in the same table.
    pulled = {
        "campaign_data": [
            {"id": "111", "analyticsResponse": {"views": 10}},
            {"id": "222", "error": "pull_failed"},
        ]
    }
    await stage_tenant_pull("hub_a", pulled)

    rows = fake_base.written["CampaignMetrics"]
    assert len(rows) == 1
    assert rows[0]["Source ID"] == "111"


@pytest.mark.asyncio
async def test_campaign_crm_records_and_campaign_metrics_go_to_separate_tables(fake_base):
    # pull_all() sets both "CAMPAIGN" (plain CRM properties, from
    # pull_crm_objects) and "campaign_data" (engagement metrics, from
    # pull_campaign_data) for a tenant with real campaigns — they must not
    # land in the same table, since one row shape isn't the other's.
    pulled = {
        "CAMPAIGN": [{"id": "111", "properties": {"hs_name": "Spring Sale"}}],
        "campaign_data": [{"id": "111", "analyticsResponse": {"views": 10}}],
    }
    await stage_tenant_pull("hub_a", pulled)

    assert len(fake_base.written["Campaigns"]) == 1
    assert len(fake_base.written["CampaignMetrics"]) == 1
    assert fake_base.written["Campaigns"][0]["Source ID"] == "111"
    assert fake_base.written["CampaignMetrics"][0]["Source ID"] == "111"


@pytest.mark.asyncio
async def test_hubspot_object_index_isolated_per_tenant_even_with_same_object_id(fake_base):
    await stage_tenant_pull("hub_a", {"list_companies": {"id": "dup-id"}})
    await stage_tenant_pull("hub_b", {"list_companies": {"id": "dup-id"}})

    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT hub_id FROM hubspot_object_index WHERE object_type = 'company' AND object_id = 'dup-id'"
    )
    hub_ids = {row["hub_id"] for row in rows}
    assert hub_ids == {"hub_a", "hub_b"}


@pytest.mark.asyncio
async def test_run_staging_cycle_survives_failure_listing_tenants(monkeypatch):
    """Regression test: get_installed_hub_ids() used to sit outside any
    try/except in run_staging_cycle, so a failure there would escape the
    function entirely instead of being logged and recorded the same way
    every other failure in this function is."""
    monkeypatch.setattr(
        airtable_staging, "get_installed_hub_ids", AsyncMock(side_effect=RuntimeError("db unreachable"))
    )
    # run_staging_cycle now delegates the "record this failure, best-effort"
    # step to the shared auth.record_audit_best_effort helper (see
    # auth/security.py) rather than calling record_audit directly.
    best_effort_mock = AsyncMock()
    monkeypatch.setattr(airtable_staging, "record_audit_best_effort", best_effort_mock)

    await run_staging_cycle()  # must not raise

    best_effort_mock.assert_awaited_once()
    args, kwargs = best_effort_mock.call_args
    assert args[0] == "staging_cycle_failed"
    assert kwargs["detail"]["stage"] == "list_tenants"
