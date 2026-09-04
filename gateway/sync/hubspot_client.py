"""Per-tenant client for HubSpot's plain REST API (api.hubapi.com), using
the Public App's own vaulted OAuth token (auth.vault) — never a second
credential. Replaces the prior mcp.hubspot.com-based implementation
(openspec/changes/hubspot-rest-api-pivot; see that change's design.md for
the full reasoning behind the pivot).

REST's endpoint set is fixed and documented by HubSpot ahead of time, so
this module has no runtime tool-discovery/classification step the way the
MCP-based version needed (no equivalent of list_tools()/_is_read_safe) —
every endpoint this project calls is a hand-enumerated constant below,
reviewed once, not discovered per call. This module only ever issues GET
requests, except one narrowly-scoped, explicitly-flagged read-only POST
(HubSpot's own Lists "search" endpoint takes filter criteria in the
request body, a real-only operation despite the HTTP verb) — matching the
read-only-absolute rule everywhere else in this project.

Several real API families, not one uniform dialect the way MCP's
query_crm_data was — confirmed live during this change's own research:
- Core CRM objects (contacts, companies, deals, etc.): `/crm/v3/objects/{type}`.
- Custom/standard property discovery: `/crm/v3/properties/{type}`.
- Campaigns: `/marketing/v3/campaigns` (its own object shape, its own
  per-campaign metrics endpoint).
- Landing pages / blog posts: HubSpot's CMS API.
- Lists (segments): HubSpot's Lists API.
- Owners, teams/account info: `/crm/v3/owners`, `/settings/v3/users*`,
  `/account-info/v3/details`.
- Marketing email analytics: `/marketing/v3/emails/statistics/list`.
- Content analytics: `/analytics/v2/reports/...`.
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone

import httpx
import structlog

from auth import vault

logger = structlog.get_logger()

HUBSPOT_API_BASE = "https://api.hubapi.com"

# Bounds pull_campaign_data()'s per-campaign concurrency — campaign count
# varies per tenant and is unbounded, unlike CRM_OBJECT_TYPES's fixed,
# small size, so it's the one gather() in this module that needs an
# explicit cap to avoid bursting HubSpot's rate limits on a tenant with
# many campaigns.
_MAX_CONCURRENT_CAMPAIGN_PULLS = 5

# Core + reference object set from spec Section 4.4 / the confirmed grant.
# Names kept identical to the prior MCP-based module so every downstream
# caller (frameworks/, session/live_session.py, sync/airtable_staging.py)
# needs no changes — only how each type is actually fetched changes below.
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
    "QUOTE",
    "OBJECT_LIST",
    "LANDING_PAGE",
    "BLOG_POST",
    "CAMPAIGN",
]

# The real REST path segment for each standard CRM object type — HubSpot's
# well-documented v3 CRM Objects API plural-name convention
# (`/crm/v3/objects/{slug}`). "users" is medium-confidence relative to the
# others (contacts/companies/deals/etc. are extremely well-established;
# the Users object's own REST access pattern is less uniformly documented)
# — confirmed live in task 2.2, see openspec/changes/hubspot-rest-api-pivot.
CRM_OBJECT_REST_SLUGS = {
    "CONTACT": "contacts",
    "COMPANY": "companies",
    "DEAL": "deals",
    "TICKET": "tickets",
    "LINE_ITEM": "line_items",
    "PRODUCT": "products",
    "CALL": "calls",
    "EMAIL": "emails",
    "MEETING_EVENT": "meetings",
    "NOTE": "notes",
    "TASK": "tasks",
    "USER": "users",
    # Two frameworks (Services/Project, Transactional — Blu Mountain's own
    # vertical documentation) name Quotes as a secondary Opportunity/
    # Proposal-stage signal. Access is tiered/migration-state dependent
    # (HubSpot is mid-migration off the legacy Quotes API toward Revenue
    # Hub), similar to CAMPAIGN's own account-tier gate — confirmed via
    # HubSpot's own docs, not yet confirmed live on either test portal.
    # crm.objects.quotes.read is requested as an optional scope for
    # exactly this reason (see HUBSPOT_OPTIONAL_SCOPES).
    "QUOTE": "quotes",
}

# These four don't share the standard CRM Objects API shape at all — each
# lives under its own API family (Marketing Campaigns, CMS, Lists) and is
# handled by its own adapter method inside pull_crm_objects(), not the
# generic /crm/v3/objects/ loop.
_NON_STANDARD_OBJECT_TYPES = {"OBJECT_LIST", "LANDING_PAGE", "BLOG_POST", "CAMPAIGN"}

# Three of the four (everything except OBJECT_LIST, which is a POST with
# its own hasMore/offset pagination shape — see _pull_lists) differ from
# each other only by endpoint path; one shared method reads from this
# instead of three near-identical one-line methods.
_NON_STANDARD_OBJECT_PATHS = {
    "CAMPAIGN": "/marketing/v3/campaigns",
    "LANDING_PAGE": "/cms/v3/pages/landing-pages",
    "BLOG_POST": "/cms/v3/blogs/posts",
}

# Natural-language query terms a caller (session/live_session.py's
# category tools) might use for each type, since CRM_OBJECT_TYPES entries
# are code-facing constants, not what a staff member would type. A naive
# substring check against the type name alone misses irregular plurals
# ("companies" is not a substring of "COMPANY") and compound/underscored
# names ("meetings" vs "MEETING_EVENT"). Every CRM_OBJECT_TYPES entry must
# have an entry here — see test_crm_object_aliases_cover_every_object_type.
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
    "QUOTE": {"quote", "quotes"},
    "OBJECT_LIST": {"list", "lists", "segment", "segments"},
    "LANDING_PAGE": {"landing_page", "landing_pages", "landing page", "landing pages"},
    "BLOG_POST": {"blog_post", "blog_posts", "blog post", "blog posts"},
    "CAMPAIGN": {"campaign", "campaigns"},
}


def resolve_object_type_aliases(text: str) -> list[str]:
    """Every canonical `CRM_OBJECT_TYPES` name that free-text `text`
    (case-insensitive — an exact canonical name or any alias in
    `CRM_OBJECT_ALIASES`) matches. Shared by `debug_api.py` and
    `session/live_session.py`, which previously each independently
    re-derived the same free-text-to-canonical-type matching.
    Ambiguity-preserving (returns every match, not just one) to match
    `live_session.py`'s own existing behavior — a caller needing exactly
    one match (`debug_api.py`) takes `[0]` with its own length check.

    Checks the exact canonical name in addition to `CRM_OBJECT_ALIASES`
    membership because they're not always the same thing — confirmed
    directly: `OBJECT_LIST`'s own lowered form ("object_list") isn't
    itself one of its aliases ("list"/"lists"/"segment"/"segments"), so a
    caller literally passing "OBJECT_LIST" needs this second check to
    match at all. Confirmed no alias string is ever shared by two
    different canonical types, so adding this check can only ever add a
    match, never create a false ambiguity that wasn't already possible."""
    lowered = text.strip().lower()
    matches = [t for t in CRM_OBJECT_TYPES if lowered in CRM_OBJECT_ALIASES.get(t, set())]
    if lowered.upper() in CRM_OBJECT_TYPES and lowered.upper() not in matches:
        matches.append(lowered.upper())
    return matches


# "teams" has no CRM_OBJECT_TYPES entry at all — its only real path is
# the organization_details generic capability below. A free-text query
# for "team"/"teams" needs translating to "organization" before matching
# against generic capability names.
GENERIC_TOOL_QUERY_ALIASES = {"team": "organization", "teams": "organization"}

# Category groupings (openspec/changes/separate-vertical-client-agents,
# task 6.1): every CRM_OBJECT_TYPES entry maps to exactly one category, so
# session/live_session.py's category-scoped tools never silently drop an
# object type. Unchanged by the REST pivot.
CATEGORY_CRM_RECORDS = "crm_records"
CATEGORY_ENGAGEMENT_RECORDS = "engagement_records"
CATEGORY_MARKETING_CONTENT = "marketing_content"
CATEGORY_USERS = "users"

OBJECT_TYPE_CATEGORIES = {
    "CONTACT": CATEGORY_CRM_RECORDS,
    "COMPANY": CATEGORY_CRM_RECORDS,
    "DEAL": CATEGORY_CRM_RECORDS,
    "TICKET": CATEGORY_CRM_RECORDS,
    "LINE_ITEM": CATEGORY_CRM_RECORDS,
    "PRODUCT": CATEGORY_CRM_RECORDS,
    "QUOTE": CATEGORY_CRM_RECORDS,
    "CALL": CATEGORY_ENGAGEMENT_RECORDS,
    "EMAIL": CATEGORY_ENGAGEMENT_RECORDS,
    "MEETING_EVENT": CATEGORY_ENGAGEMENT_RECORDS,
    "NOTE": CATEGORY_ENGAGEMENT_RECORDS,
    "TASK": CATEGORY_ENGAGEMENT_RECORDS,
    "CAMPAIGN": CATEGORY_MARKETING_CONTENT,
    "LANDING_PAGE": CATEGORY_MARKETING_CONTENT,
    "BLOG_POST": CATEGORY_MARKETING_CONTENT,
    "OBJECT_LIST": CATEGORY_MARKETING_CONTENT,
    "USER": CATEGORY_USERS,
}

# Generic (non-CRM-object) read capabilities this project implements via
# REST, each its own adapter method below — the fixed, hand-maintained
# replacement for the prior MCP-based dynamic tool discovery. Assigned to
# exactly one category, same posture as CRM_OBJECT_TYPES.
CATEGORY_GENERIC_CAPABILITIES = {
    CATEGORY_USERS: {"owners", "organization_details"},
    CATEGORY_MARKETING_CONTENT: {"content_analytics", "marketing_email_analytics", "campaign_attribution"},
    CATEGORY_CRM_RECORDS: set(),
    CATEGORY_ENGAGEMENT_RECORDS: set(),
}

_SAFE_PROPERTY_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _is_safe_property_name(name: str) -> bool:
    """True only for a plain identifier. Defense in depth for the
    `properties=` query param: these names already come from HubSpot's
    own properties endpoint, never raw caller input, but the same "don't
    trust scope/intent alone" posture this project has always held
    applies here too."""
    return bool(_SAFE_PROPERTY_NAME_RE.match(name))


_SAFE_OBJECT_TYPE_ID_RE = re.compile(r"^\d+-\d+$")


def _is_safe_object_type_id(object_type_id: str) -> bool:
    """True only for HubSpot's real objectTypeId shape (e.g. "2-3465404").
    Same defense-in-depth posture as _is_safe_property_name: a custom
    object's objectTypeId always comes from HubSpot's own schema-discovery
    response, never raw external input, before it's interpolated into a
    URL path — but this project doesn't trust "it's internal" alone
    anywhere else either (openspec/changes/custom-object-support)."""
    return bool(_SAFE_OBJECT_TYPE_ID_RE.match(object_type_id))


class ReadOnlyViolation(Exception):
    """Raised if a call would reach a write-shaped HubSpot endpoint."""


class HubSpotRateLimited(Exception):
    """Raised when HubSpot returns 429 for a request this module made."""


class HubSpotDataPullClient:
    """One instance per pull; never shares a connection or token across tenants."""

    def __init__(self, hub_id: str) -> None:
        self.hub_id = hub_id

    def log_pull_failure(self, tool: str, exc: Exception) -> None:
        """Public (no leading underscore) so other callers of this class's
        pull methods (e.g. session/live_session.py's category tools) log a
        failed call under the same hubspot_pull.tool_failed event name and
        field convention every other pull-failure path uses."""
        logger.error("hubspot_pull.tool_failed", hub_id=self.hub_id, tool=tool, error=str(exc))

    async def _client_for_hub(self) -> tuple[httpx.AsyncClient, dict]:
        access_token = await vault.get_access_token(self.hub_id)
        return httpx.AsyncClient(timeout=30.0), {"Authorization": f"Bearer {access_token}"}

    async def _headers_for(self, client_was_provided: bool) -> dict:
        """When a caller passes its own `client` (reusing one connection
        across several calls, see pull_all()), this project still needs
        that tenant's own current token for the Authorization header —
        vault.get_access_token()'s own cache makes the extra lookup cheap
        (a lock-free Postgres read unless the token is near expiry)."""
        access_token = await vault.get_access_token(self.hub_id)
        return {"Authorization": f"Bearer {access_token}"}

    async def _resolve_client_and_headers(
        self, client: httpx.AsyncClient | None, headers: dict | None
    ) -> tuple[httpx.AsyncClient, dict, bool]:
        """Shared resolve step for the leaf methods whose resolve-failure and
        body-failure degrade to the identical value and log tag
        (`_fetch_property_definitions`, `discover_custom_object_schemas`,
        `pull_custom_object`, `pull_object`) — collapses their repeated
        `owns_client = client is None; if owns_client: ... elif headers is
        None: ...` block into one call. Returns `(client, headers,
        owns_client)`; the caller still owns closing the client via `if
        owns_client: await client.aclose()`, and must compute `owns_client
        = client is None` itself *before* calling this (not from this
        method's return value), since a raised exception here leaves the
        caller's own `client` variable unchanged.

        Deliberately not used by `pull_crm_objects`/`pull_campaign_data`:
        both have an *asymmetric* guard today (only the owns-client branch
        is wrapped in try/except; the `elif headers is None` branch is not),
        so merging their resolve step behind one try/except the way this
        helper's callers do would newly catch a failure that currently
        propagates — a real behavior change, not just deduplication."""
        owns_client = client is None
        if owns_client:
            client, headers = await self._client_for_hub()
        elif headers is None:
            headers = await self._headers_for(client_was_provided=True)
        return client, headers, owns_client

    async def _paginate(
        self, client: httpx.AsyncClient, headers: dict, path: str, params: dict, results_key: str = "results"
    ) -> list[dict]:
        """Follows HubSpot's standard v3 cursor pagination (`paging.next.after`)
        until exhausted. Every standard CRM object list endpoint, and
        several of the generic-capability endpoints below, share this
        exact shape."""
        records: list[dict] = []
        cursor = None
        while True:
            call_params = dict(params)
            if cursor:
                call_params["after"] = cursor
            response = await client.get(f"{HUBSPOT_API_BASE}{path}", headers=headers, params=call_params)
            if response.status_code == 429:
                raise HubSpotRateLimited(path)
            response.raise_for_status()
            body = response.json()
            records.extend(body.get(results_key, []))
            cursor = body.get("paging", {}).get("next", {}).get("after")
            if not cursor:
                break
        return records

    # --- core CRM objects: /crm/v3/objects/{slug} ---

    async def pull_crm_objects(
        self,
        client: httpx.AsyncClient | None = None,
        object_types: list[str] | None = None,
        properties: dict[str, list[str]] | None = None,
        headers: dict | None = None,
    ) -> dict[str, object]:
        """Pulls every requested CRM object type. Standard types
        (CRM_OBJECT_REST_SLUGS) go through `/crm/v3/objects/{slug}`; the
        four non-standard types (CAMPAIGN, LANDING_PAGE, BLOG_POST,
        OBJECT_LIST) route to their own adapter methods, since they live
        under entirely different HubSpot API families. All object types
        are pulled concurrently — each is independent and already
        isolates its own failure into its own result key.

        properties: an optional {object_type: [property_name, ...]} map.
        When given for a standard object type, the REST `properties=`
        query param is set to exactly those names — confirmed live
        (openspec/changes/hubspot-rest-api-pivot, task 2.3) that REST's
        `properties` parameter is a true explicit selection, unlike the
        prior MCP-based mechanism's additive behavior. Omitting it (or
        `properties=None` entirely) keeps HubSpot's own default set.

        headers: lets a caller that already resolved this tenant's
        Authorization header (e.g. pull_all(), which resolves it once for
        an entire multi-call pull) pass it straight through instead of
        this method fetching it again from the vault — vault.get_access_token
        caches, so a second fetch was never incorrect, just a needless
        extra Postgres round trip on every call. Only consulted when
        `client` is also given; irrelevant (and unused) on the
        owns-its-own-client path, which always resolves both together."""
        types = object_types if object_types is not None else CRM_OBJECT_TYPES
        owns_client = client is None
        if owns_client:
            try:
                client, headers = await self._client_for_hub()
            except Exception as exc:
                self.log_pull_failure("token_fetch", exc)
                return {"error": "pull_failed"}
        elif headers is None:
            headers = await self._headers_for(client_was_provided=True)

        async def _pull_one(object_type: str) -> tuple[str, object]:
            try:
                if object_type in _NON_STANDARD_OBJECT_TYPES:
                    # These four don't go through the CRM Objects API's
                    # `properties=` mechanism at all (each lives under its
                    # own API family with no equivalent field-narrowing
                    # param this project has wired up) — a caller that
                    # requested one anyway gets the unfiltered response,
                    # not silently: logged here so it's discoverable
                    # rather than an invisible no-op.
                    if (properties or {}).get(object_type):
                        logger.warning(
                            "hubspot_client.properties_ignored_for_non_standard_type",
                            hub_id=self.hub_id,
                            object_type=object_type,
                        )
                    if object_type in _NON_STANDARD_OBJECT_PATHS:
                        return object_type, await self._pull_non_standard_object(
                            _NON_STANDARD_OBJECT_PATHS[object_type], client, headers
                        )
                    if object_type == "OBJECT_LIST":
                        return object_type, await self._pull_lists(client, headers)
                    raise KeyError(
                        f"{object_type!r} is in _NON_STANDARD_OBJECT_TYPES but has no dispatch branch here"
                    )

                slug = CRM_OBJECT_REST_SLUGS[object_type]
                params = {"limit": 100}
                requested = (properties or {}).get(object_type)
                if requested:
                    safe = [p for p in requested if _is_safe_property_name(p)]
                    if safe:
                        params["properties"] = ",".join(safe)
                records = await self._paginate(client, headers, f"/crm/v3/objects/{slug}", params)
                return object_type, records
            except Exception as exc:
                self.log_pull_failure(f"crm_objects:{object_type}", exc)
                return object_type, {"error": "pull_failed"}

        try:
            pairs = await asyncio.gather(*(_pull_one(object_type) for object_type in types))
            return dict(pairs)
        finally:
            if owns_client:
                await client.aclose()

    # --- custom/standard property discovery: /crm/v3/properties/{slug} ---

    async def discover_object_properties(
        self, object_type: str, client: httpx.AsyncClient | None = None, headers: dict | None = None
    ) -> list[str]:
        """Returns every real property name for one object type on this
        tenant's portal, including custom (portal-specific) properties —
        via REST's `/crm/v3/properties/{slug}`, which (unlike the prior
        MCP-based search_properties) returns every property for the type
        in one call with no keyword-search step needed."""
        definitions = await self.discover_object_property_definitions(object_type, client=client, headers=headers)
        return [d["name"] for d in definitions]

    async def discover_object_property_definitions(
        self, object_type: str, client: httpx.AsyncClient | None = None, headers: dict | None = None
    ) -> list[dict]:
        """Like discover_object_properties, but returns each property's
        full definition, including REST's own authoritative `hubspotDefined`
        boolean — the real signal this project's prior is_custom_property_name()
        heuristic existed only because MCP's search_properties didn't expose
        it (openspec/changes/hubspot-rest-api-pivot, task 3.2)."""
        slug = CRM_OBJECT_REST_SLUGS.get(object_type)
        if slug is None:
            return []
        return await self._fetch_property_definitions(slug, f"properties:{object_type}", client, headers)

    async def _fetch_property_definitions(
        self,
        slug_or_object_type_id: str,
        log_tool_name: str,
        client: httpx.AsyncClient | None = None,
        headers: dict | None = None,
    ) -> list[dict]:
        """The actual `GET /crm/v3/properties/{slug}` fetch+parse, shared
        by discover_object_property_definitions (standard objects, keyed
        by a CRM_OBJECT_REST_SLUGS slug) and discover_custom_object_properties
        (custom objects, keyed by a runtime-discovered objectTypeId) —
        REST's properties endpoint works identically either way, confirmed
        live (openspec/changes/custom-object-support). A token-fetch
        failure (e.g. an unknown/never-installed tenant) degrades to []
        the same way an HTTP-level failure does — never propagates
        uncaught out of a method whose whole contract is "never crash,
        just return what it can.\""""
        owns_client = client is None
        try:
            client, headers, owns_client = await self._resolve_client_and_headers(client, headers)
            response = await client.get(
                f"{HUBSPOT_API_BASE}/crm/v3/properties/{slug_or_object_type_id}", headers=headers
            )
            response.raise_for_status()
            body = response.json()
            return [
                {"name": r["name"], "hubspotDefined": bool(r.get("hubspotDefined"))}
                for r in body.get("results", [])
                if isinstance(r, dict) and _is_safe_property_name(r.get("name", ""))
            ]
        except Exception as exc:
            self.log_pull_failure(log_tool_name, exc)
            return []
        finally:
            if owns_client and client is not None:
                await client.aclose()

    # --- custom objects: runtime-discovered, never a fixed slug
    # (openspec/changes/custom-object-support) ---

    async def discover_custom_object_schemas(
        self, client: httpx.AsyncClient | None = None, headers: dict | None = None
    ) -> list[dict]:
        """Every custom object schema defined on this tenant's portal,
        discovered fresh per call — there is no fixed lookup table for
        these the way CRM_OBJECT_REST_SLUGS is for standard objects, since
        a custom object is defined per-portal, at runtime, by whoever
        configured that client's HubSpot instance. Returns each schema's
        `objectTypeId` (the identifier every other method here needs),
        `name`, and `labels`. A different path prefix than every other
        endpoint in this module (`crm-object-schemas/v3`, not `crm/v3`) —
        confirmed live against HubSpot's own docs, not assumed. Degrades
        to `[]` on a portal without Custom Objects access (an Enterprise-
        tier HubSpot feature) rather than raising — confirmed live the
        baseline-tier test portal can't even create a custom object at
        all, let alone grant this scope. A token-fetch failure degrades
        the same way an HTTP-level failure does."""
        owns_client = client is None
        try:
            client, headers, owns_client = await self._resolve_client_and_headers(client, headers)
            response = await client.get(f"{HUBSPOT_API_BASE}/crm-object-schemas/v3/schemas", headers=headers)
            response.raise_for_status()
            body = response.json()
            return [
                {
                    "objectTypeId": r["objectTypeId"],
                    "name": r.get("name"),
                    "labels": r.get("labels"),
                }
                for r in body.get("results", [])
                if isinstance(r, dict) and _is_safe_object_type_id(r.get("objectTypeId", ""))
            ]
        except Exception as exc:
            self.log_pull_failure("custom_object_schemas", exc)
            return []
        finally:
            if owns_client and client is not None:
                await client.aclose()

    async def pull_custom_object(
        self,
        object_type_id: str,
        client: httpx.AsyncClient | None = None,
        headers: dict | None = None,
        properties: list[str] | None = None,
    ) -> list[dict] | dict:
        """Reads one custom object's records by its `objectTypeId` (from
        discover_custom_object_schemas — there is no friendly-name lookup
        for a custom object the way CRM_OBJECT_ALIASES resolves one for
        standard types; a caller must discover the identifier first).
        Same paginated GET /crm/v3/objects/{objectTypeId} shape as every
        standard object already pulled — REST's Objects API doesn't
        distinguish standard from custom here, only the identifier
        differs. Returns `{"error": "pull_failed"}` (not a raised
        exception) on failure, matching every other object-family adapter
        in this module."""
        if not _is_safe_object_type_id(object_type_id):
            return {"error": "pull_failed"}
        owns_client = client is None
        try:
            client, headers, owns_client = await self._resolve_client_and_headers(client, headers)
            params = {"limit": 100}
            safe_properties = [p for p in (properties or []) if _is_safe_property_name(p)]
            if safe_properties:
                params["properties"] = ",".join(safe_properties)
            return await self._paginate(client, headers, f"/crm/v3/objects/{object_type_id}", params)
        except Exception as exc:
            self.log_pull_failure(f"custom_object:{object_type_id}", exc)
            return {"error": "pull_failed"}
        finally:
            if owns_client and client is not None:
                await client.aclose()

    async def discover_custom_object_properties(
        self, object_type_id: str, client: httpx.AsyncClient | None = None, headers: dict | None = None
    ) -> list[dict]:
        """Every real property defined on one custom object, keyed by its
        `objectTypeId` — reuses the exact same `GET /crm/v3/properties/{type}`
        mechanism discover_object_property_definitions already uses for
        standard objects; REST's properties endpoint works identically
        for a custom object's objectTypeId, confirmed live."""
        if not _is_safe_object_type_id(object_type_id):
            return []
        return await self._fetch_property_definitions(
            object_type_id, f"custom_object_properties:{object_type_id}", client, headers
        )

    # --- non-standard object families ---

    async def _pull_non_standard_object(self, path: str, client: httpx.AsyncClient, headers: dict) -> list[dict]:
        """Shared GET+paginate for the non-standard object families whose
        only difference from each other is the endpoint path (Marketing
        Campaigns, CMS landing pages, CMS blog posts — see
        `_NON_STANDARD_OBJECT_PATHS`). Account-tier gating (e.g. Campaigns
        requiring a paid marketing tier) degrades gracefully here the same
        way the prior MCP-based path did: a real 403/401 from HubSpot is
        caught by `pull_crm_objects()`'s own outer try/except, not
        specially handled here. `OBJECT_LIST` stays its own method
        (`_pull_lists`) — a POST with its own hasMore/offset pagination
        shape, not this GET+cursor one."""
        return await self._paginate(client, headers, path, {"limit": 100})

    async def _pull_lists(self, client: httpx.AsyncClient, headers: dict) -> list[dict]:
        """HubSpot's Lists API. Its own "search" operation is a POST (filter
        criteria go in the request body) but is a real, read-only search —
        this project's one deliberate exception to "GET only," reviewed and
        flagged explicitly rather than silently allowed.

        Paginated via this endpoint's own hasMore/offset response fields
        (not the standard paging.next.after cursor shape _paginate
        handles — the Lists Search endpoint uses a different pagination
        convention), looping until hasMore is false. Confirmed via
        HubSpot's own API reference: the response's `offset` value is fed
        back as the next request's `offset`. Without this loop, a tenant
        with more than 100 real lists would silently lose everything past
        the first page."""
        results: list[dict] = []
        offset = 0
        while True:
            response = await client.post(
                f"{HUBSPOT_API_BASE}/crm/v3/lists/search",
                headers=headers,
                json={"count": 100, "offset": offset},
            )
            if response.status_code == 429:
                raise HubSpotRateLimited("/crm/v3/lists/search")
            response.raise_for_status()
            body = response.json()
            results.extend(body.get("lists", []))
            if not body.get("hasMore"):
                break
            offset = body.get("offset", offset)
        return results

    # --- per-campaign metrics ---

    async def pull_campaign_data(
        self, client: httpx.AsyncClient | None = None, headers: dict | None = None
    ) -> list[dict]:
        """Pulls attribution metrics for every real campaign in this
        tenant's portal via `/marketing/v3/campaigns/{campaignGuid}/reports/metrics`
        — unlike a plain campaign list, every one of these calls needs a
        specific campaign GUID, so campaigns are enumerated first, then
        each is queried for metrics, concurrently but bounded."""
        owns_client = client is None
        if owns_client:
            try:
                client, headers = await self._client_for_hub()
            except Exception as exc:
                self.log_pull_failure("token_fetch", exc)
                return []
        elif headers is None:
            headers = await self._headers_for(client_was_provided=True)

        try:
            try:
                campaigns = await self._paginate(client, headers, "/marketing/v3/campaigns", {"limit": 100})
            except Exception as exc:
                self.log_pull_failure("campaigns:list", exc)
                return []

            campaign_guids = [c.get("id") for c in campaigns if isinstance(c, dict) and c.get("id")]
            semaphore = asyncio.Semaphore(_MAX_CONCURRENT_CAMPAIGN_PULLS)

            async def _pull_one(campaign_guid: str) -> dict:
                async with semaphore:
                    try:
                        response = await client.get(
                            f"{HUBSPOT_API_BASE}/marketing/v3/campaigns/{campaign_guid}/reports/metrics",
                            headers=headers,
                        )
                        response.raise_for_status()
                        record = response.json()
                        record["id"] = campaign_guid
                        return record
                    except Exception as exc:
                        self.log_pull_failure(f"campaign_metrics:{campaign_guid}", exc)
                        return {"id": campaign_guid, "error": "pull_failed"}

            return list(await asyncio.gather(*(_pull_one(g) for g in campaign_guids)))
        finally:
            if owns_client:
                await client.aclose()

    # --- generic capabilities (formerly MCP's dynamic tools) ---

    @staticmethod
    async def list_read_only_tools(client: httpx.AsyncClient | None = None) -> list[str]:
        """Returns this project's fixed, hand-maintained set of generic
        read capability names — the REST-era replacement for the prior
        MCP-based dynamic tool discovery. No live discovery call is made;
        REST's endpoint set is known ahead of time, so what's "available"
        is simply what this module implements. Never reads `self.hub_id`
        (there is no `self`) — a `@staticmethod` since this doesn't need
        a tenant-scoped instance at all; `client` stays accepted, unused,
        purely so existing instance-style call sites that pass one for
        connection-reuse consistency don't need to change."""
        return list(_GENERIC_CAPABILITIES.keys())

    async def pull_object(
        self, tool_name: str, client: httpx.AsyncClient | None = None, headers: dict | None = None, **params
    ) -> dict:
        """Calls one named generic capability for this tenant — the
        REST-era replacement for calling an MCP tool by name. `tool_name`
        must be one of list_read_only_tools()'s fixed set; anything else
        raises ReadOnlyViolation before any HubSpot call is made.
        Degrades to {"error": "pull_failed"} on any other failure (a
        token-fetch problem or the capability's own HubSpot call failing),
        matching every other leaf pull method in this file — a caller
        that doesn't independently wrap this call still gets the
        "never crash, just degrade" guarantee."""
        capability = _GENERIC_CAPABILITIES.get(tool_name)
        if capability is None:
            raise ReadOnlyViolation(f"Refusing to call unrecognized capability: {tool_name}")

        owns_client = client is None
        try:
            client, headers, owns_client = await self._resolve_client_and_headers(client, headers)
            return await capability(self, client, headers, **params)
        except Exception as exc:
            self.log_pull_failure(tool_name, exc)
            return {"error": "pull_failed"}
        finally:
            if owns_client and client is not None:
                await client.aclose()

    async def _owners(self, client: httpx.AsyncClient, headers: dict, **_params) -> list[dict]:
        """`/crm/v3/owners/` — the REST equivalent of the prior
        search_owners MCP tool."""
        return await self._paginate(client, headers, "/crm/v3/owners/", {"limit": 100})

    async def _organization_details(self, client: httpx.AsyncClient, headers: dict, **_params) -> dict:
        """Composed from three real, independently-scoped REST endpoints —
        the equivalent of the prior get_organization_details MCP tool,
        which itself bundled teams, seats/users, and account info into
        one call. REST doesn't have one bundled endpoint for this, so
        this assembles the same shape from `/settings/v3/users/teams`,
        `/settings/v3/users/`, and `/account-info/v3/details`.

        Each call degrades independently to {"error": "pull_failed"} for
        just its own key rather than failing the whole method — confirmed
        live that `/settings/v3/users/teams` needs its own scope distinct
        from `/settings/v3/users/`, so a portal missing just that one
        scope would otherwise lose the other two endpoints' real data too
        even though they'd have succeeded on their own."""

        async def _get(path: str) -> dict:
            try:
                response = await client.get(f"{HUBSPOT_API_BASE}{path}", headers=headers)
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                self.log_pull_failure(f"organization_details:{path}", exc)
                return {"error": "pull_failed"}

        teams, users, account = await asyncio.gather(
            _get("/settings/v3/users/teams"),
            _get("/settings/v3/users/"),
            _get("/account-info/v3/details"),
        )
        return {"teams": teams, "users": users, "account": account}

    async def _content_analytics(self, client: httpx.AsyncClient, headers: dict, **_params) -> dict:
        """`/analytics/v2/reports/pages/total` — the REST equivalent of
        the prior get_content_analytics_report MCP tool. HubSpot's
        Analytics API is v2, not v3, and less uniformly documented than
        the CRM APIs — confirmed real and callable, moderate rather than
        high confidence relative to the CRM endpoints above."""
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=30)
        response = await client.get(
            f"{HUBSPOT_API_BASE}/analytics/v2/reports/pages/total",
            headers=headers,
            params={"start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d")},
        )
        response.raise_for_status()
        return response.json()

    async def _marketing_email_analytics(self, client: httpx.AsyncClient, headers: dict, **_params) -> dict:
        """`/marketing/v3/emails/statistics/list` — confirmed real REST
        endpoint (this change's own research) for the prior
        get_marketing_email_analytics MCP tool."""
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=30)
        response = await client.get(
            f"{HUBSPOT_API_BASE}/marketing/v3/emails/statistics/list",
            headers=headers,
            params={"startTimestamp": start.isoformat(), "endTimestamp": end.isoformat()},
        )
        response.raise_for_status()
        return response.json()

    async def _campaign_attribution(self, client: httpx.AsyncClient, headers: dict, **_params) -> dict:
        """Aggregates `/marketing/v3/campaigns/{id}/reports/metrics`
        across every real campaign — the REST equivalent of the prior
        get_campaign_attribution_reports MCP tool, which returned a
        portal-wide rollup from one call; REST has no single bundled
        rollup endpoint, so this assembles one from the same per-campaign
        metrics pull_campaign_data() already does."""
        records = await self.pull_campaign_data(client=client, headers=headers)
        return {"campaigns": records}

    async def pull_all(self) -> dict[str, object]:
        """Pulls every in-scope, read-only object type for this tenant —
        the generic capabilities, the CRM object set, and per-campaign
        metrics. Tenant context is fixed at construction time
        (self.hub_id), so every call in this method is scoped to exactly
        one tenant's vaulted token. Opens exactly one httpx.AsyncClient
        for the whole pull, reused across every call."""
        try:
            client, headers = await self._client_for_hub()
        except Exception as exc:
            self.log_pull_failure("token_fetch", exc)
            return {"error": "pull_failed"}

        async def _pull_generic(tool_name: str) -> tuple[str, object]:
            try:
                return tool_name, await self.pull_object(tool_name, client=client, headers=headers)
            except Exception as exc:
                self.log_pull_failure(tool_name, exc)
                return tool_name, {"error": "pull_failed"}

        try:
            # "campaign_attribution" is excluded here specifically: it's
            # just pull_campaign_data() wrapped in a {"campaigns": [...]}
            # envelope (see _campaign_attribution's docstring), and this
            # method already calls pull_campaign_data() directly below for
            # the "campaign_data" key — including it in the generic loop
            # too would pull every campaign's metrics twice per cycle for
            # no new data. It stays fully reachable as its own capability
            # everywhere else (list_read_only_tools, pull_object,
            # session/live_session.py's category tools) — this exclusion
            # is scoped to pull_all()'s own redundant-work concern only,
            # the same posture the prior MCP-based pull_all() held toward
            # PER_ITEM_TOOLS.
            tool_names = [
                name for name in await self.list_read_only_tools(client=client) if name != "campaign_attribution"
            ]
            generic_pairs, crm_results, campaign_results = await asyncio.gather(
                asyncio.gather(*(_pull_generic(name) for name in tool_names)),
                self.pull_crm_objects(client=client, headers=headers),
                self.pull_campaign_data(client=client, headers=headers),
            )
        finally:
            await client.aclose()

        results: dict[str, object] = dict(generic_pairs)
        results.update(crm_results)
        results["campaign_data"] = campaign_results
        return results


_GENERIC_CAPABILITIES = {
    "owners": HubSpotDataPullClient._owners,
    "organization_details": HubSpotDataPullClient._organization_details,
    "content_analytics": HubSpotDataPullClient._content_analytics,
    "marketing_email_analytics": HubSpotDataPullClient._marketing_email_analytics,
    "campaign_attribution": HubSpotDataPullClient._campaign_attribution,
}
