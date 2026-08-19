"""Per-tenant client for HubSpot's remote MCP endpoint (mcp.hubspot.com).

Connects with FastMCP as an MCP client, authenticated with that tenant's
vaulted MCP Auth App access token (auth.mcp_vault, spec Section 4.1) — not
the Public App's token used elsewhere in this project, since mcp.hubspot.com
is its own OAuth resource server (confirmed via its RFC 9728/8414 metadata)
and does not accept the Public App's CRM-scoped token. Reads only the
in-scope, read-only object set.

Three distinct read paths, confirmed live against the real endpoint (see
design.md's decision log):

1. Generic per-object tools (e.g. analytics/reporting tools), discovered
   dynamically via list_tools() rather than hardcoded, since HubSpot does
   not publish a fixed tool-name contract. A tool is only ever called if
   its name both looks read-safe (no recognized write verb) AND matches a
   recognized read verb — the read-verb allowlist isn't a defensive extra,
   it's load-bearing: this module authenticates with the MCP Auth App's
   token (auth.mcp_vault), a separate credential from the Public App's
   OAuth-scoped token (.env.example's HUBSPOT_SCOPES) — the MCP Auth App
   has no per-object scope grant of its own to rely on at all, so this
   dynamic filter is the only thing standing between "HubSpot published a
   tool that matches our read/in-scope keywords" and an actual call. Some
   of these need a fixed default parameter their own schema requires
   (_DEFAULT_TOOL_PARAMS) — confirmed live, none of these tools need
   anything caller-supplied, just a value this module always sends the
   same way.
2. The core CRM object set (contacts, companies, deals, tickets, etc.) has
   no per-object tool at all — confirmed live, the only way to read any of
   it is `query_crm_data`, one generic tool that takes a raw SQL-like
   string. Tool-name filtering can't gate this one (the object type lives
   in the SQL text, not the tool name), so it's handled entirely
   separately by pull_crm_objects(): the SQL is always authored here, from
   a fixed per-type template, never passed through from any caller, and is
   still run through _is_safe_select() as defense in depth even though we
   wrote it ourselves — the same "don't rely on scope alone" posture as
   the read-verb allowlist above.
3. Per-campaign metrics via read_campaign_data — unlike every tool above,
   every one of its operations requires a specific campaignCrmObjectId, so
   there's no single fixed default the way path 1's tools have. Handled
   separately by pull_campaign_data(): enumerate real campaign IDs via
   query_crm_data first, then call once per campaign.
"""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import structlog
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from auth import mcp_vault

logger = structlog.get_logger()

HUBSPOT_MCP_URL = "https://mcp.hubspot.com"

# Bounds pull_campaign_data()'s per-campaign concurrency — campaign count
# varies per tenant and is unbounded, unlike CRM_OBJECT_TYPES's fixed,
# small size, so it's the one gather() in this module that needs an
# explicit cap to avoid bursting HubSpot's rate limits on a tenant with
# many campaigns.
_MAX_CONCURRENT_CAMPAIGN_PULLS = 5

# Core + reference object set from spec Section 4.4 / the confirmed grant.
# "organization" is here specifically for get_organization_details (see
# list_read_only_tools()) — its name mentions neither "team" nor "user",
# but it's the only real path to the spec's "teams" reference object
# (confirmed live: query_crm_data has no queryable TEAM type at all).
IN_SCOPE_OBJECT_KEYWORDS = [
    "contact",
    "compan",
    "deal",
    "ticket",
    "line_item",
    "line item",
    "product",
    "call",
    "email",
    "meeting",
    "note",
    "task",
    "user",
    "team",
    "owner",
    "campaign",
    "content",
    "list",
    "organization",
]

# The real, confirmed FROM-clause type names for query_crm_data (see
# pull_crm_objects()), discovered live via discover_hubspot_schema's
# GET_OBJECT_TYPES — not guessed from the spec's plain-English object
# names, which don't all match (e.g. "meetings" is MEETING_EVENT, not
# MEETING). Covers the spec's "landing pages" and "blog posts" too
# (LANDING_PAGE, BLOG_POST) — both are plain queryable object types here,
# the same mechanism as every other entry, not something that needed
# HubSpot's separate, read/write-mixed manage_landing_page tool. CAMPAIGN
# is included too — confirmed live against a real Enterprise-tier test
# account (see pull_campaign_data() below for why campaign *metrics* need
# a separate per-campaign path instead of a plain SELECT). "teams" is the
# one spec object with no queryable type in this list at all — it's read
# via the separate get_organization_details tool instead (see
# IN_SCOPE_OBJECT_KEYWORDS above), not through query_crm_data.
CRM_OBJECT_TYPES = [
    "CONTACT",
    "COMPANY",
    "DEAL",
    "TICKET",
    "LINE_ITEM",
    "PRODUCT",
    "CALL",
    "EMAIL",
    "MEETING_EVENT",
    "NOTE",
    "TASK",
    "USER",
    "OBJECT_LIST",
    "LANDING_PAGE",
    "BLOG_POST",
    "CAMPAIGN",
]

# Natural-language query terms a caller (session/live_session.py's
# query_hubspot_data) might use for each type, since CRM_OBJECT_TYPES
# entries are code-facing constants, not what a staff member would type.
# A naive substring check against the type name alone misses irregular
# plurals ("companies" is not a substring of "COMPANY", nor vice versa —
# the plural changes "y" to "ies", not just appends a letter) and
# compound/underscored names ("meetings" vs "MEETING_EVENT", "landing
# pages" vs "LANDING_PAGE"). Every CRM_OBJECT_TYPES entry must have an
# entry here — see test_crm_object_aliases_cover_every_object_type, which
# asserts that correspondence statically so a future new object type can't
# silently go unmatched the way "companies"/"meetings" did.
CRM_OBJECT_ALIASES = {
    "CONTACT": {"contact", "contacts"},
    "COMPANY": {"company", "companies", "compan"},
    "DEAL": {"deal", "deals"},
    "TICKET": {"ticket", "tickets"},
    "LINE_ITEM": {"line_item", "line_items", "line item", "line items"},
    "PRODUCT": {"product", "products"},
    "CALL": {"call", "calls"},
    "EMAIL": {"email", "emails"},
    "MEETING_EVENT": {"meeting", "meetings", "meeting_event", "meeting_events"},
    "NOTE": {"note", "notes"},
    "TASK": {"task", "tasks"},
    "USER": {"user", "users"},
    "OBJECT_LIST": {"list", "lists", "segment", "segments"},
    "LANDING_PAGE": {"landing_page", "landing_pages", "landing page", "landing pages"},
    "BLOG_POST": {"blog_post", "blog_posts", "blog post", "blog posts"},
    "CAMPAIGN": {"campaign", "campaigns"},
}

# "teams" has no CRM_OBJECT_TYPES entry at all — its only real path is the
# generic tool get_organization_details (see IN_SCOPE_OBJECT_KEYWORDS's own
# "organization" entry below). A free-text query for "team"/"teams" needs
# translating to "organization" before matching against tool names, or it
# never finds get_organization_details the same way IN_SCOPE_OBJECT_KEYWORDS
# already does for the scheduled pull.
GENERIC_TOOL_QUERY_ALIASES = {"team": "organization", "teams": "organization"}

# query_crm_data (see pull_crm_objects()) is deliberately never in the
# generic dynamic allowlist below: its tool name reveals neither the
# object type (that's in the SQL text) nor read/write intent the way
# "get_x"/"create_x" names do, so name-based filtering can't gate it
# safely. _is_safe_select() is its own, SQL-text-level guard instead.
_SQL_QUERY_TOOLS = {"query_crm_data"}

# read_campaign_data's name passes the generic read-verb/in-scope checks
# below just fine (matches "read" and "campaign"), but every one of its
# operations requires a specific campaignCrmObjectId — there's no single
# fixed default call the way the other generic tools have, so pull_all()
# skips it here and pull_campaign_data() handles it separately: enumerate
# real campaign IDs first, then call once per campaign. Public (no leading
# underscore) so other callers of list_read_only_tools()/pull_object()
# (e.g. session/live_session.py) can exclude it the same way, instead of
# rediscovering "read_campaign_data needs special handling" independently.
PER_ITEM_TOOLS = {"read_campaign_data"}

# Deliberately broad: this is the sole enforcement point for the MCP Auth
# App's token (it carries no OAuth scope of its own, unlike the Public
# App's HUBSPOT_SCOPES), so a name containing a recognized read verb
# ("get_and_send_email", "search_and_enroll_contacts") must still be
# rejected if it also contains ANY of these — the read-verb allowlist
# alone isn't enough once a name can carry both. Still a hand-curated
# blocklist, not a provable-complete one, against an API this project
# doesn't control: HubSpot could ship a tool whose write-shaped verb isn't
# here yet. list_read_only_tools()'s logging is the backstop for a name
# that gets EXCLUDED unexpectedly, but there is no equivalent backstop for
# one that gets INCLUDED unexpectedly — treat any newly-selected tool name
# as worth a human glance against HubSpot's real catalog before trusting
# it, the same "confirmed live" standard this project holds everything
# else to.
_WRITE_VERBS = {
    "create", "update", "upsert", "delete", "remove", "archive", "write",
    "patch", "put", "merge", "enroll", "unenroll", "subscribe",
    "unsubscribe", "send", "publish", "unpublish", "schedule", "cancel",
    "restore", "move", "assign", "unassign", "close", "resolve", "reopen",
    "associate", "disassociate", "share", "unshare", "revoke", "grant",
    "execute", "run", "trigger", "dispatch", "clone", "duplicate", "import",
    "rollback", "approve", "reject", "block", "unblock", "lock", "unlock",
    "transfer", "convert", "split", "apply", "deactivate", "activate",
    "enable", "disable", "reset", "push", "bulk",
}

# Blocks any SQL keyword that could mutate data, matched as a whole SQL
# token (see _is_safe_select) so this can never be defeated by embedding
# one of these words inside an identifier or string literal instead.
# Deliberately excludes "call" despite being a plausible
# stored-procedure-style keyword elsewhere: CALL is itself a real HubSpot
# object type name (CRM_OBJECT_TYPES), and this dialect has no documented
# procedure-call syntax to guard against in the first place. Also
# deliberately excludes "into"/"set": both are only meaningful as part of
# INSERT INTO / UPDATE ... SET, and those parent statement keywords are
# already blocked below — "into"/"set" alone can't start a write statement
# in this dialect, but they ARE common enough as bare English words or
# identifier components (e.g. a "job_offer_set" property, a literal
# containing "mind set") that keeping them here would false-positive-reject
# a legitimate SELECT for no real safety gain.
_SQL_WRITE_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "truncate", "merge",
    "create", "grant", "revoke", "replace", "exec", "execute",
}

# A tool name must contain one of these to be treated as read-safe. This is
# deliberately an allowlist, not just the write-verb blocklist above: this
# module's token (auth.mcp_vault, the MCP Auth App's credential) carries no
# per-object scope grant at all, unlike the Public App's HUBSPOT_SCOPES, so
# this function is the only enforcement of read-only for every tool it
# calls, not a defensive extra on top of a scope that already refuses
# writes. A blocklist alone fails open — an unrecognized tool name (e.g.
# a hypothetical "notify_owner" or "flag_deal", containing no word in
# _WRITE_VERBS and no read verb either) would slip through as "safe"
# purely because nothing matched. Requiring a recognized read verb too
# means an unrecognized name fails closed instead: it's excluded from
# pull_all()'s results (less data) rather than risking a write going
# through (a non-negotiable violation). See list_read_only_tools()'s
# logging for whichever in-scope tools this excludes in practice, once
# connected to HubSpot's real endpoint. This still doesn't catch a name
# that has BOTH a recognized read verb and an unlisted write verb (e.g.
# "get_and_send_email") — that's exactly what the broadened _WRITE_VERBS
# above exists to close as much as a hand-curated list can.
_READ_VERBS = {"get", "list", "search", "fetch", "find", "retrieve", "read", "describe"}


def _marketing_email_overview_params() -> dict:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=30)
    return {
        "mode": {
            "_type": "OVERVIEW",
            "statisticsSection": {
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "frequency": "TOTAL",
            },
        }
    }


# get_campaign_attribution_reports's own schema lists no required fields,
# but it runtime-rejects an empty call ("At least one metric is
# required") and separately requires hasReadToolInstructions=true to skip
# a one-time instructions round-trip aimed at an LLM caller reading them
# fresh each session — not useful for this scheduled job, which always
# sends the same fixed call, so it's set true unconditionally. Confirmed
# live against a real Enterprise-tier test account with a real campaign:
# on a portal where Campaigns isn't enabled at all (REQUIRES_ACCOUNT_
# MODIFICATION, see design.md's decision log), this still fails with
# "Not Authorized" — an account-tier gate this default can't and
# shouldn't try to work around, correctly caught and logged per-tenant by
# pull_all()'s existing error handling rather than failing the whole pull.
def _campaign_attribution_params() -> dict:
    return {"metrics": ["REVENUE", "DEAL_COUNT"], "hasReadToolInstructions": True}


# Confirmed live: neither tool requires any parameter to return a
# meaningful default (a portal-wide rollup), but both have a truly
# required field their own schema rejects an empty call without —
# get_content_analytics_report needs `mode`, get_marketing_email_analytics
# needs a `mode` object with a date range. pull_all() looks a tool up here
# before calling it with no other params; anything not listed gets none,
# same as before. read_campaign_data is deliberately NOT here — every one
# of its operations requires a specific campaignCrmObjectId, so it can't
# take a single fixed default the way these can; see pull_campaign_data().
_DEFAULT_TOOL_PARAMS = {
    "get_content_analytics_report": lambda: {"mode": "TOTALS"},
    "get_marketing_email_analytics": _marketing_email_overview_params,
    "get_campaign_attribution_reports": _campaign_attribution_params,
}


class ReadOnlyViolation(Exception):
    """Raised if a tool that looks like a write operation would otherwise be called."""


def _tool_name_words(tool_name: str) -> list[str]:
    # Split on non-letter characters so snake_case/kebab-case tool names
    # (e.g. "create_contact") are checked word-by-word. A plain \b-based
    # regex does NOT catch this: underscore counts as a \w character, so
    # \bcreate\b never matches inside "create_contact".
    return re.split(r"[^a-zA-Z]+", tool_name.lower())


def _has_write_verb(tool_name: str) -> bool:
    return any(word in _WRITE_VERBS for word in _tool_name_words(tool_name))


def _is_read_safe(tool_name: str) -> bool:
    if _has_write_verb(tool_name):
        return False
    return any(word in _READ_VERBS for word in _tool_name_words(tool_name))


def _is_in_scope(tool_name: str) -> bool:
    lowered = tool_name.lower()
    return any(keyword in lowered for keyword in IN_SCOPE_OBJECT_KEYWORDS)


def _extract_result(result) -> object:
    """Returns a tool call's real payload. Confirmed live across every one
    of HubSpot's 20 real MCP tools: none declares an outputSchema, so
    FastMCP's result.data/.structured_content are always None — the real
    payload is JSON text inside the first content block instead. Falls
    back to result.data first regardless, in case that ever changes for a
    given tool, rather than assuming it will always be unset."""
    if result.data is not None:
        return result.data
    if not result.content:
        return None
    text = getattr(result.content[0], "text", None)
    if text is None:
        return result.content
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _unwrap_query_crm_data(value: object) -> object:
    """query_crm_data's real response (confirmed live) wraps each record in
    a citation-oriented envelope distinct from other tools' plain JSON
    objects: {"results": [{"content": "<json-encoded record>"}, ...],
    "instructions": "..."} — "instructions" is LLM-facing guidance, not
    data, and each result's "content" is itself a JSON-encoded string, not
    a dict. Flattens this to a plain list of record dicts."""
    if not isinstance(value, dict) or "results" not in value:
        return value

    records = []
    for item in value.get("results", []):
        content = item.get("content") if isinstance(item, dict) else item
        if isinstance(content, str):
            try:
                records.append(json.loads(content))
                continue
            except (TypeError, ValueError):
                pass
        records.append(content)
    return records


def _is_safe_select(sql: str) -> bool:
    """True only for a single, plain SELECT statement with no write-shaped
    keyword anywhere in it. This is defense in depth, not the primary
    control — pull_crm_objects() only ever constructs "SELECT * FROM
    {TYPE}" itself, never from caller input — but the tickets read-verb
    allowlist above establishes this project's own precedent of not
    trusting scope/intent alone, so the same posture applies here."""
    stripped = sql.strip()
    if not re.match(r"(?is)^select\b", stripped):
        return False

    # Reject anything after a first semicolon (stacked statements), a
    # single optional trailing semicolon is fine.
    body = stripped[:-1] if stripped.endswith(";") else stripped
    if ";" in body:
        return False

    words = set(re.split(r"[^a-zA-Z]+", body.lower()))
    return not (words & _SQL_WRITE_KEYWORDS)


class HubSpotDataPullClient:
    """One instance per pull; never shares a connection or token across tenants."""

    def __init__(self, hub_id: str) -> None:
        self.hub_id = hub_id

    async def _client(self, access_token: str) -> Client:
        # auth takes the raw token; FastMCP applies the "Bearer " scheme itself.
        transport = StreamableHttpTransport(url=HUBSPOT_MCP_URL, auth=access_token)
        return Client(transport)

    def log_pull_failure(self, tool: str, exc: Exception) -> None:
        """Public (no leading underscore) so other callers of this class's
        pull methods (e.g. session/live_session.py's query_hubspot_data)
        log a failed tool call under the same hubspot_pull.tool_failed
        event name and field convention every other pull-failure path
        uses, instead of inventing a second, differently-named one."""
        logger.error("hubspot_pull.tool_failed", hub_id=self.hub_id, tool=tool, error=str(exc))

    async def list_read_only_tools(self, client: Client | None = None) -> list[str]:
        """Returns in-scope, read-safe tool names for this tenant's portal.
        Reuses `client` if given (see pull_all()); opens and closes its own
        connection otherwise, for standalone callers."""
        if client is not None:
            tools = await client.list_tools()
        else:
            access_token = await mcp_vault.get_access_token(self.hub_id)
            async with await self._client(access_token) as owned_client:
                tools = await owned_client.list_tools()

        selected = []
        write_shaped = []
        unrecognized_no_read_verb = []
        read_safe_but_out_of_scope = []
        for tool in tools:
            name = tool.name
            if _has_write_verb(name):
                write_shaped.append(name)
            elif not _is_read_safe(name):
                unrecognized_no_read_verb.append(name)
            elif _is_in_scope(name):
                selected.append(name)
            else:
                read_safe_but_out_of_scope.append(name)

        if write_shaped:
            logger.warning(
                "hubspot_pull.write_tools_excluded", hub_id=self.hub_id, count=len(write_shaped)
            )
        if unrecognized_no_read_verb:
            # Excluded only because the name didn't match a recognized read
            # verb, not because it looked like a write — worth reviewing once
            # connected to the real endpoint, in case a legitimate read tool
            # is being missed and _READ_VERBS needs another entry.
            logger.warning(
                "hubspot_pull.unrecognized_tools_excluded",
                hub_id=self.hub_id,
                count=len(unrecognized_no_read_verb),
                tool_names=unrecognized_no_read_verb,
            )
        if read_safe_but_out_of_scope:
            # Read-safe, but doesn't match any in-scope object keyword — not
            # a safety concern (nothing unsafe is excluded here), but this
            # branch used to log nothing at all, which is exactly how
            # get_organization_details (the real path to the spec's "teams"
            # object) went unnoticed for a while. Logged at info, not
            # warning, since exclusion here is expected for genuinely
            # out-of-scope tools (e.g. search_conversations, a HubSpot inbox
            # feature never named in spec Section 4.4) as well as ones that
            # do need reviewing.
            logger.info(
                "hubspot_pull.out_of_scope_tools_excluded",
                hub_id=self.hub_id,
                count=len(read_safe_but_out_of_scope),
                tool_names=read_safe_but_out_of_scope,
            )
        return selected

    async def pull_object(self, tool_name: str, client: Client | None = None, **params) -> dict:
        """Calls a single read-only tool for this tenant. Raises ReadOnlyViolation
        if the tool name suggests a write operation (or, for query_crm_data,
        if its sql parameter isn't a plain SELECT), never calls it. Reuses
        `client` if given (see pull_all()); opens and closes its own
        connection otherwise, for standalone callers."""
        if tool_name in _SQL_QUERY_TOOLS:
            if not _is_safe_select(params.get("sql", "")):
                raise ReadOnlyViolation(
                    f"Refusing non-SELECT SQL for {tool_name}: {params.get('sql', '')!r}"
                )
        elif not _is_read_safe(tool_name):
            raise ReadOnlyViolation(f"Refusing to call non-read-only tool: {tool_name}")

        if client is not None:
            result = await client.call_tool(tool_name, params)
        else:
            access_token = await mcp_vault.get_access_token(self.hub_id)
            async with await self._client(access_token) as owned_client:
                result = await owned_client.call_tool(tool_name, params)
        value = _extract_result(result)
        if tool_name in _SQL_QUERY_TOOLS:
            value = _unwrap_query_crm_data(value)
        return value

    async def pull_crm_objects(
        self, client: Client | None = None, object_types: list[str] | None = None
    ) -> dict[str, object]:
        """Pulls every confirmed-real CRM object type (CRM_OBJECT_TYPES) via
        query_crm_data — the one tool that can read contacts, companies,
        deals, tickets, etc. (see this module's docstring for why these
        can't go through list_read_only_tools()'s generic name-based
        filter). Each query is a fixed "SELECT hs_object_id, * FROM {TYPE}"
        authored here, never from external input. All object types are
        pulled concurrently — each is independent and already isolates its
        own failure into its own result key, so there's nothing
        serialization would protect here, only latency it would add.

        hs_object_id is selected explicitly, not left to "*" alone —
        confirmed live that HubSpot's default property set for every CRM
        object type excludes its own object ID, and "id" isn't a valid
        property name at all (HubSpot's own error names hs_object_id as
        the real one). Without it, every pulled row is missing the one
        field sync.airtable_staging._index_crm_objects needs to populate
        hubspot_object_index, which is what Sybill's tenant resolution
        looks up — confirmed live: that table stayed empty for every
        tenant this pulled, with no error anywhere in the pull itself,
        since a missing Source ID is silently skipped, not raised.

        object_types defaults to the full CRM_OBJECT_TYPES (pull_all()'s
        use), but a caller that only needs a subset (session/live_session.py's
        query_hubspot_data, matching a staff member's free-text query) can
        pass just those — reusing this exact SQL-construction and
        failure-handling logic instead of re-implementing it."""
        types = object_types if object_types is not None else CRM_OBJECT_TYPES

        async def _pull_one(object_type: str) -> tuple[str, object]:
            sql = f"SELECT hs_object_id, * FROM {object_type}"
            try:
                return object_type, await self.pull_object("query_crm_data", client=client, sql=sql)
            except Exception as exc:
                self.log_pull_failure(f"query_crm_data:{object_type}", exc)
                return object_type, {"error": "pull_failed"}

        pairs = await asyncio.gather(*(_pull_one(object_type) for object_type in types))
        return dict(pairs)

    async def pull_campaign_data(self, client: Client | None = None) -> list[dict]:
        """Pulls engagement metrics for every real campaign in this
        tenant's portal via read_campaign_data — unlike every other tool
        in this module, every one of its operations requires a specific
        campaignCrmObjectId, so there's no single fixed default call the
        way get_campaign_attribution_reports has (see _DEFAULT_TOOL_PARAMS).
        Enumerates real campaign IDs via query_crm_data first (graceful,
        empty result if CAMPAIGN isn't accessible on this tenant's account
        tier — see design.md's decision log), then calls read_campaign_data
        once per campaign, concurrently. Confirmed live against a real
        Enterprise-tier test account with a real campaign.

        Returns a list of per-campaign records (each carrying its own "id"),
        not a dict keyed by campaign ID — this is staged into Airtable's
        Campaigns table the same way every other object type is
        (sync/airtable_staging.py's stage_tenant_pull expects a list of
        records or a single record, not an ID-keyed mapping)."""
        try:
            campaigns = await self.pull_object(
                "query_crm_data", client=client, sql="SELECT hs_object_id, hs_name FROM CAMPAIGN"
            )
        except Exception as exc:
            self.log_pull_failure("query_crm_data:CAMPAIGN_IDS", exc)
            return []

        campaign_ids = []
        for campaign in campaigns or []:
            properties = campaign.get("properties", {}) if isinstance(campaign, dict) else {}
            campaign_id = properties.get("hs_object_id")
            # Identity check, not truthiness — a real hs_object_id of "0"
            # (unlikely but not impossible) must not be dropped the way a
            # missing one is.
            if campaign_id is not None:
                campaign_ids.append(campaign_id)

        # Bounded, not one call per campaign in an unbounded single burst —
        # a tenant with a large campaign count would otherwise fire
        # dozens/hundreds of concurrent requests at mcp.hubspot.com with no
        # outbound throttling anywhere on this path, risking rate-limit
        # errors that show up indistinguishable from genuine per-item
        # failures.
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_CAMPAIGN_PULLS)

        async def _pull_one(campaign_id: str) -> dict:
            async with semaphore:
                try:
                    metrics = await self.pull_object(
                        "read_campaign_data",
                        client=client,
                        operation="GET_ANALYTICS",
                        analyticsRequest={
                            "requests": [
                                {"campaignCrmObjectId": int(campaign_id), "requestedData": "METRICS"}
                            ]
                        },
                    )
                    record = dict(metrics) if isinstance(metrics, dict) else {"metrics": metrics}
                    record["id"] = campaign_id
                    return record
                except Exception as exc:
                    self.log_pull_failure(f"read_campaign_data:{campaign_id}", exc)
                    return {"id": campaign_id, "error": "pull_failed"}

        return list(await asyncio.gather(*(_pull_one(campaign_id) for campaign_id in campaign_ids)))

    async def pull_all(self) -> dict[str, object]:
        """Pulls every in-scope, read-only object type for this tenant —
        the generic per-object tools, the CRM object set via
        query_crm_data, and per-campaign metrics. Tenant context is fixed
        at construction time (self.hub_id), so every call in this method
        is scoped to exactly one tenant's vaulted token.

        Opens exactly one MCP connection for the whole pull (instead of one
        per tool/object call) and runs the three independent groups of
        work — generic tools, CRM objects, campaign data — concurrently,
        rather than strictly sequentially, since none of them depend on
        each other's results."""
        try:
            access_token = await mcp_vault.get_access_token(self.hub_id)
            client = await self._client(access_token)
        except Exception as exc:
            # Most plausibly a tenant that has completed only the Public
            # App install and not yet the MCP Auth App install (a valid,
            # documented interim state — see context/ONBOARDING_RUNBOOK.md)
            # — logged under the same event name as every other per-tool
            # failure so operators checking for hubspot_pull.tool_failed
            # find it here too, instead of only a generic cycle-level error.
            self.log_pull_failure("mcp_auth_connect", exc)
            return {"error": "pull_failed"}

        async with client:
            try:
                tool_names = await self.list_read_only_tools(client=client)
            except Exception as exc:
                self.log_pull_failure("list_tools", exc)
                return {"error": "pull_failed"}

            async def _pull_generic(tool_name: str) -> tuple[str, object]:
                try:
                    default_params = _DEFAULT_TOOL_PARAMS.get(tool_name)
                    params = default_params() if default_params else {}
                    return tool_name, await self.pull_object(tool_name, client=client, **params)
                except Exception as exc:
                    self.log_pull_failure(tool_name, exc)
                    return tool_name, {"error": "pull_failed"}

            generic_tool_names = [name for name in tool_names if name not in PER_ITEM_TOOLS]

            generic_pairs, crm_results, campaign_results = await asyncio.gather(
                asyncio.gather(*(_pull_generic(name) for name in generic_tool_names)),
                self.pull_crm_objects(client=client),
                self.pull_campaign_data(client=client),
            )

        results: dict[str, object] = dict(generic_pairs)
        results.update(crm_results)
        results["campaign_data"] = campaign_results
        return results
