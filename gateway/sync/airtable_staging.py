"""Airtable staging: schema, normalization, and the scheduled pull-and-stage cycle.

One table per in-scope HubSpot object type, plus one for Sybill transcripts.
Each table carries a small set of indexed columns (client tag, source ID,
sync time) and a full JSON payload column, so the complete standard field
set survives staging without a hand-modeled column per HubSpot field.
Every record is tagged by client (hub_id) on write (SC-10, FR-11).
"""

import json
from datetime import datetime, timezone

import structlog
from pyairtable import Api

from auth import check_rate_limit, get_installed_hub_ids, record_audit, record_audit_best_effort
from config import settings
from db import get_pool

from .hubspot_client import HubSpotDataPullClient

logger = structlog.get_logger()

# Canonical table per in-scope object category. Keys match the keyword
# classification already used in hubspot_client.IN_SCOPE_OBJECT_KEYWORDS —
# every keyword there needs a matching entry here, or that object type is
# pulled from HubSpot successfully and then silently dropped before ever
# reaching Airtable (exactly how "organization"/LANDING_PAGE/BLOG_POST went
# unstaged for a while: hubspot_client.py's keyword list had them, this one
# didn't).
OBJECT_TABLES = {
    "contact": "Contacts",
    "compan": "Companies",
    "deal": "Deals",
    "ticket": "Tickets",
    "line_item": "LineItems",
    "line item": "LineItems",
    "product": "Products",
    "quote": "Quotes",
    "call": "Calls",
    # Checked before the plain "email" entry below (dict order matters:
    # _table_for_tool returns the FIRST matching keyword) — the
    # marketing_email_analytics generic capability returns one portal-wide
    # stats dict, a structurally different shape from EMAIL's real
    # per-engagement CRM records, so it needs its own table rather than
    # silently collapsing into "Emails" (the same reasoning as
    # campaign_data/campaign directly below).
    "marketing_email_analytics": "MarketingEmailAnalytics",
    "email": "Emails",
    "meeting": "Meetings",
    "note": "Notes",
    "task": "Tasks",
    "user": "Users",
    "team": "Teams",
    # get_organization_details is the real path to the "teams" object (see
    # hubspot_client.py's IN_SCOPE_OBJECT_KEYWORDS) — its name matches
    # neither "team" nor "user", so it needs its own keyword here too,
    # routed into the same Teams table.
    "organization": "Teams",
    "owner": "Owners",
    # Checked before the plain "campaign" entry below (dict order matters:
    # _table_for_tool returns the FIRST matching keyword) — pull_all()'s
    # "campaign_data" key (pull_campaign_data()'s per-campaign engagement
    # metrics) is a structurally different record shape than "CAMPAIGN"
    # (pull_crm_objects()'s plain CRM properties for the same object), so
    # they need separate tables, not one shared "Campaigns" table holding
    # two incompatible row shapes under the same Source ID.
    "campaign_data": "CampaignMetrics",
    "campaign": "Campaigns",
    "content": "Content",
    "list": "Lists",
    "landing_page": "LandingPages",
    "blog_post": "BlogPosts",
}

SYBILL_TABLE = "SybillTranscripts"

# openspec/changes/vertical-diagnostic-agent: one diagnostic-phase report
# per row, tagged by client — its own table rather than reusing
# OBJECT_TABLES/_STAGING_FIELDS, since a report's shape (summary/KPIs/risk
# flags) is structurally unrelated to a raw HubSpot object payload.
DIAGNOSTIC_REPORTS_TABLE = "DiagnosticReports"

_STAGING_FIELDS = [
    {"name": "Client", "type": "singleLineText"},
    {"name": "Source ID", "type": "singleLineText"},
    {"name": "Object Type", "type": "singleLineText"},
    {"name": "Data", "type": "multilineText"},
    {"name": "Synced At", "type": "dateTime", "options": {
        "dateFormat": {"name": "iso"}, "timeFormat": {"name": "24hour"}, "timeZone": "utc"
    }},
]

_DIAGNOSTIC_REPORT_FIELDS = [
    {"name": "Client", "type": "singleLineText"},
    {"name": "Vertical", "type": "singleLineText"},
    {"name": "Summary", "type": "multilineText"},
    {"name": "KPIs", "type": "multilineText"},
    {"name": "Risk Flags", "type": "multilineText"},
    {"name": "Generated At", "type": "dateTime", "options": {
        "dateFormat": {"name": "iso"}, "timeFormat": {"name": "24hour"}, "timeZone": "utc"
    }},
]


def _table_for_tool(tool_name: str) -> str | None:
    lowered = tool_name.lower()
    for keyword, table_name in OBJECT_TABLES.items():
        if keyword in lowered:
            return table_name
    return None


def _api() -> Api:
    return Api(settings.airtable_api_key)


def ensure_schema() -> None:
    """Creates any missing staging tables. Idempotent; uses schema.bases:write."""
    api = _api()
    base = api.base(settings.airtable_base_id)
    existing = {t.name for t in base.schema().tables}

    for table_name in list(dict.fromkeys(OBJECT_TABLES.values())) + [SYBILL_TABLE]:
        if table_name in existing:
            continue
        base.create_table(name=table_name, fields=_STAGING_FIELDS)
        logger.info("airtable_staging.table_created", table=table_name)

    if DIAGNOSTIC_REPORTS_TABLE not in existing:
        base.create_table(name=DIAGNOSTIC_REPORTS_TABLE, fields=_DIAGNOSTIC_REPORT_FIELDS)
        logger.info("airtable_staging.table_created", table=DIAGNOSTIC_REPORTS_TABLE)


def normalize_record(hub_id: str, object_type: str, raw: dict) -> dict:
    """Normalizes one HubSpot object into a staging row, tagged by client.

    ID extraction prefers raw["properties"]["hs_object_id"] over a
    top-level "id" key. Confirmed live: query_crm_data's CRM object records
    (COMPANY, DEAL — the path sync.hubspot_client.pull_crm_objects always
    selects hs_object_id for) have no top-level "id" field at all, and "id"
    isn't even a valid property name for any CRM object type; hs_object_id
    is the real one. The generic per-object tools (e.g.
    get_organization_details) and campaign_data's per-campaign records use
    a top-level "id" instead — confirmed separately, during this
    project's earlier live testing — so that's kept as the fallback rather
    than replaced, to avoid silently breaking an already-verified path on
    an assumption from a different tool family."""
    source_id = ""
    if isinstance(raw, dict):
        properties = raw.get("properties")
        hs_object_id = properties.get("hs_object_id") if isinstance(properties, dict) else None
        source_id = str(hs_object_id) if hs_object_id else str(raw.get("id", "") or "")
    return {
        "Client": hub_id,
        "Source ID": source_id,
        "Object Type": object_type,
        "Data": json.dumps(raw, default=str),
        "Synced At": datetime.now(timezone.utc).isoformat(),
    }


def normalize_sybill_transcript(hub_id: str, payload: dict) -> dict:
    """Normalizes an accepted Sybill webhook payload for staging (FR-12)."""
    return {
        "Client": hub_id,
        "Source ID": str(payload.get("objectId", "")),
        "Object Type": payload.get("eventType", "sybill.meeting"),
        "Data": json.dumps(payload, default=str),
        "Synced At": datetime.now(timezone.utc).isoformat(),
    }


def normalize_diagnostic_report(hub_id: str, vertical: str, report: dict) -> dict:
    """Normalizes one diagnostic-phase report (openspec/changes/vertical-
    diagnostic-agent) into a staging row, tagged by client. KPIs and risk
    flags are stored as JSON text — like every other staged payload's Data
    column — rather than modeled as Airtable's own array/multi-select
    field types, so a framework's KPI shape can vary without a schema
    migration."""
    return {
        "Client": hub_id,
        "Vertical": vertical,
        "Summary": report.get("summary", ""),
        "KPIs": json.dumps(report.get("kpis", []), default=str),
        "Risk Flags": json.dumps(report.get("risk_flags", []), default=str),
        "Generated At": datetime.now(timezone.utc).isoformat(),
    }


async def stage_diagnostic_report(hub_id: str, vertical: str, report: dict) -> None:
    """Stages one diagnostic-phase report into Airtable, tagged by client —
    the same per-tenant, tagged-by-client convention as stage_tenant_pull.
    Raises on failure rather than swallowing it: the caller (the
    live-session diagnostic tool) is responsible for logging/auditing a
    staging failure distinctly from a successful stage, per this
    capability's own spec requirement."""
    api = _api()
    base = api.base(settings.airtable_base_id)
    table = base.table(DIAGNOSTIC_REPORTS_TABLE)
    table.create(normalize_diagnostic_report(hub_id, vertical, report))
    logger.info("airtable_staging.diagnostic_report_staged", hub_id=hub_id, vertical=vertical)


async def stage_tenant_pull(hub_id: str, pulled: dict[str, object]) -> None:
    """Writes one tenant's pulled data into Airtable, grouped by table, tagged
    by client. Records are batch-created per table so one tenant's write
    never touches another tenant's rows (isolation is enforced by the fact
    that every row here carries only this call's hub_id, never another's)."""
    api = _api()
    base = api.base(settings.airtable_base_id)

    by_table: dict[str, list[dict]] = {}
    for tool_name, result in pulled.items():
        table_name = _table_for_tool(tool_name)
        if table_name is None:
            continue
        records = result if isinstance(result, list) else [result]
        for record in records:
            if not isinstance(record, dict) or "error" in record:
                continue
            by_table.setdefault(table_name, []).append(
                normalize_record(hub_id, tool_name, record)
            )

    for table_name, rows in by_table.items():
        table = base.table(table_name)
        table.batch_create(rows)

    await _index_crm_objects(hub_id, by_table)

    logger.info("airtable_staging.staged", hub_id=hub_id, tables=list(by_table.keys()))


async def _index_crm_objects(hub_id: str, by_table: dict[str, list[dict]]) -> None:
    """Indexes Company/Deal IDs so webhooks.sybill can resolve which tenant a
    transcript's data.crm reference belongs to. See schema.sql's
    hubspot_object_index."""
    indexable = {"Companies": "company", "Deals": "deal"}
    pool = await get_pool()
    for table_name, object_type in indexable.items():
        for row in by_table.get(table_name, []):
            source_id = row.get("Source ID")
            if not source_id:
                continue
            await pool.execute(
                """
                INSERT INTO hubspot_object_index (object_type, object_id, hub_id)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                object_type,
                source_id,
                hub_id,
            )


async def run_staging_cycle() -> None:
    """The scheduled job: pulls, normalizes, and writes every active tenant's
    data end to end (FR-11). Runs on SYNC_INTERVAL_MINUTES via APScheduler."""
    try:
        hub_ids = await get_installed_hub_ids()
    except Exception as exc:
        # Same reasoning as the per-tenant except block below: this used to
        # sit outside any try/except at all, so a failure here (most
        # plausibly a Postgres blip) would escape straight to APScheduler's
        # own internal logger instead of this project's audit_log — now
        # caught the same way every other failure in this function is.
        logger.error("airtable_staging.cycle_failed_to_list_tenants", error=str(exc))
        await record_audit_best_effort("staging_cycle_failed", detail={"error": str(exc), "stage": "list_tenants"})
        return

    for hub_id in hub_ids:
        try:
            if not await check_rate_limit(hub_id):
                logger.warning("airtable_staging.rate_limited", hub_id=hub_id)
                continue

            client = HubSpotDataPullClient(hub_id)
            pulled = await client.pull_all()
            await stage_tenant_pull(hub_id, pulled)
            await record_audit("staging_cycle_completed", hub_id=hub_id, detail={"tables": list(pulled.keys())})
        except Exception as exc:
            # If record_audit_best_effort's own record_audit call fails for
            # the same reason the pull did (a Postgres outage, most
            # plausibly), letting that propagate would abort this for loop
            # entirely — silently skipping every remaining tenant in this
            # cycle, not just this one. record_audit_best_effort's shared
            # try/except (see auth/security.py) is what keeps the cycle
            # moving; the logger.error below already guarantees the
            # original failure is visible regardless.
            logger.error("airtable_staging.cycle_failed", hub_id=hub_id, error=str(exc))
            await record_audit_best_effort("staging_cycle_failed", hub_id=hub_id, detail={"error": str(exc)})
