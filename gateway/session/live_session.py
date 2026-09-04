"""Live interactive session: FastMCP's OAuth Proxy (GoogleProvider) wrapping
one manually registered Google Workspace OAuth client.

Works identically from any MCP client that speaks the standard MCP
authorization flow — Claude Desktop, Claude Code, or Claude Cowork; nothing
here is specific to any one of them.

FastMCP issues its own audience-scoped JWT (token factory pattern) to the
connecting client; Google's own token never leaves the proxy, this is what
satisfies the no-token-passthrough non-negotiable for this path.

Every tool enforces, in order: the Google Workspace domain allowlist,
default-open tenant access (every staff member who signs in successfully
has access to every installed tenant unless explicitly restricted from one
via staff_tenant_restrictions), and (when a staff member has more than one
permitted tenant) an explicit tenant selection, before any HubSpot data is
returned. Every access is audited by staff identity and tenant.
"""

import asyncio

import structlog
from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.dependencies import get_access_token

from auth import TENANT_DISPLAY_NAME_SQL, record_audit
from config import settings
from db import get_pool
from sync import HubSpotDataPullClient
from sync.hubspot_client import (
    CATEGORY_CRM_RECORDS,
    CATEGORY_ENGAGEMENT_RECORDS,
    CATEGORY_GENERIC_CAPABILITIES as CATEGORY_GENERIC_TOOLS,
    CATEGORY_MARKETING_CONTENT,
    CATEGORY_USERS,
    CRM_OBJECT_ALIASES,
    GENERIC_TOOL_QUERY_ALIASES,
    OBJECT_TYPE_CATEGORIES,
    resolve_object_type_aliases,
)

logger = structlog.get_logger()


class NotAllowedDomain(Exception):
    pass


class NoPermittedTenants(Exception):
    pass


class TenantSelectionRequired(Exception):
    pass


class TenantNotPermitted(Exception):
    pass


def _build_auth() -> GoogleProvider:
    return GoogleProvider(
        client_id=settings.fastmcp_google_client_id,
        client_secret=settings.fastmcp_google_client_secret,
        base_url=settings.fastmcp_base_url,
        required_scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"],
        # FASTMCP_ACCESS_TOKEN_TTL_MINUTES was documented in .env.example
        # ("the real revocation window") since before this project's
        # config-audit pass, but was never actually passed here — FastMCP's
        # own default expiry was silently governing every issued session
        # token instead. GoogleProvider's real parameter name is in
        # seconds, not minutes.
        fastmcp_access_token_expiry_seconds=settings.fastmcp_access_token_ttl_minutes * 60,
    )


mcp = FastMCP("Blu Mountain Live Session", auth=_build_auth())


async def _require_staff_identity() -> tuple[str, str]:
    """Returns (email, session_key) after enforcing the domain allowlist.
    session_key is the issued token's JTI, stable for this session's lifetime.
    Both email and domain use `.get(key) or ""` rather than `.get(key, "")`
    — the default in `.get(key, "")` only applies when the key is *absent*;
    a claim present with value None (a real possibility depending on the
    upstream token issuer) would otherwise reach `.lower()` and raise
    AttributeError, turning what should be a clean NotAllowedDomain
    rejection into an unhandled crash.

    Both are lowercased here, once, at the only place a staff_identity value
    ever originates in this system — so every downstream comparison
    (staff_tenant_restrictions, audit_log, live_session_selection,
    allowed_google_domains_list) is consistent regardless of the casing
    Google's claim, a hand-typed SQL restriction, or
    FASTMCP_ALLOWED_GOOGLE_DOMAINS happen to use. Under the default-open
    model an email casing mismatch would otherwise fail open (an intended
    restriction silently not applying); a domain casing mismatch would
    instead fail closed (a legitimate staff member wrongly rejected) — both
    are bugs, just in different directions.

    An empty/unconfigured allowlist fails closed (rejects everyone), not
    open (allows everyone) — under the old allow-list model a blank
    FASTMCP_ALLOWED_GOOGLE_DOMAINS was harmless, since a stranger still had
    no grant row; under default-open, this domain check is the *only* gate,
    so the safe default when it's misconfigured is to admit no one, not
    everyone.

    `hd` (the Workspace hosted-domain claim) is NOT a top-level field on the
    token FastMCP's GoogleProvider issues — confirmed live by reading its
    source: the AccessToken.claims dict it builds only has sub/aud/email/
    name/picture/given_name/family_name/locale/google_user_data, no hd. The
    real value lives inside google_user_data, the raw Google v2 userinfo
    response nested wholesale under that one key. A real login always
    passed `hd` correctly through Google's own consent screen and callback
    (visible in main.py's callback logs), but every domain check here still
    read as empty — discovered only by actually calling a tool with a real
    issued token, since every unit test for this function constructs its
    own fake token with `hd` placed at the top level, matching the wrong
    (pre-fix) assumption instead of the real shape."""
    token = get_access_token()
    email = (token.claims.get("email") or "").lower()
    google_user_data = token.claims.get("google_user_data")
    if not isinstance(google_user_data, dict):
        # Fails closed the same way a missing key does (see this
        # function's docstring) rather than crashing, in case a future
        # token ever carries a non-dict truthy value here.
        google_user_data = {}
    domain = (token.claims.get("hd") or google_user_data.get("hd") or "").lower()
    allowed = settings.allowed_google_domains_list

    if not allowed or domain not in allowed:
        logger.warning("live_session.domain_rejected", domain=domain)
        await record_audit(
            "live_domain_rejected", staff_identity=email, detail={"domain": domain}
        )
        raise NotAllowedDomain(f"Domain '{domain}' is not on the allowlist")

    session_key = token.claims.get("jti") or token.token
    return email, session_key


async def _permitted_tenants(staff_identity: str) -> list[dict]:
    """Every installed tenant, minus any explicitly restricted for this staff
    member, in a single query — not the shared get_installed_hub_ids() (used
    by the once-per-cycle scheduled sync) plus a second restrictions query,
    since this runs on every live-session tool call and the extra round
    trip matters here in a way it doesn't for the sync job. This
    deliberately re-states the install_status = 'installed' predicate
    that get_installed_hub_ids() also has, trading that narrow duplication
    for one fewer Postgres round trip on the hot path. staff_identity is
    already lowercased by the caller (_require_staff_identity); LOWER() on
    the stored column is the other half of that guarantee — a restriction
    row hand-typed with different casing must still match, not silently
    fail open just because the comparison itself was case-sensitive.

    Returns each tenant's effective display name alongside its hub_id —
    `auth.TENANT_DISPLAY_NAME_SQL` (COALESCE(portal_name, hub_domain,
    hub_id), shared with debug_api.py/onboarding.py) computed here in SQL
    so every caller sees a real, never-NULL name without re-deriving the
    same fallback chain in Python. Each candidate is wrapped in
    NULLIF(TRIM(...), '') first: an empty or whitespace-only string is not
    NULL to Postgres, so a bare COALESCE would treat a blank portal_name
    as "the real name" instead of falling through to hub_domain — the
    write path normalizes blanks to NULL too (see hubspot_oauth.py's
    /install and _persist_new_tenant), but this guards the read path
    independently rather than trusting every possible writer got it
    right. portal_name is a human-curated name (set only via /install's
    optional query param); hub_domain is HubSpot's own domain for the
    portal, auto-captured at install time (HubSpot has no API for an
    actual company/display name — confirmed against its account-info
    endpoint)."""
    pool = await get_pool()
    rows = await pool.fetch(
        f"""
        SELECT hub_id,
               {TENANT_DISPLAY_NAME_SQL} AS name
        FROM tenants
        WHERE install_status = 'installed'
          AND hub_id NOT IN (
              SELECT hub_id FROM staff_tenant_restrictions WHERE LOWER(staff_identity) = $1
          )
        """,
        staff_identity,
    )
    return [{"hub_id": row["hub_id"], "name": row["name"]} for row in rows]


def _hub_ids(permitted: list[dict]) -> set[str]:
    return {t["hub_id"] for t in permitted}


async def _deny_tenant_access(staff_identity: str, hub_id: str, reason: str) -> None:
    """Logs and audits a denied tenant-access attempt, then raises
    TenantNotPermitted. Shared by every path that rejects a specific
    hub_id, so the audit trail (the system's only record attributing a
    HubSpot read, or an attempt at one, to a specific person) can't
    silently drift between call sites."""
    logger.warning("live_session.tenant_access_denied", staff=staff_identity, hub_id=hub_id)
    await record_audit(
        "live_tenant_access_denied",
        hub_id=hub_id,
        staff_identity=staff_identity,
        detail={"reason": reason},
    )
    raise TenantNotPermitted(f"{staff_identity} is not permitted to access {hub_id}")


async def _persist_tenant_selection(staff_identity: str, session_key: str, hub_id: str) -> None:
    """Writes the selection with no re-validation — callers must already
    have confirmed hub_id is in this staff member's permitted set, so the
    auto-select path (which just computed that set) doesn't pay for
    re-deriving and re-checking it a second time via select_tenant_internal."""
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO live_session_selection (session_id, staff_identity, selected_hub_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (session_id) DO UPDATE SET selected_hub_id = EXCLUDED.selected_hub_id
        """,
        session_key,
        staff_identity,
        hub_id,
    )


async def _resolve_selected_tenant(staff_identity: str, session_key: str) -> str:
    """Returns the tenant selected for this session, auto-selecting when the
    staff member has exactly one permitted tenant, else requiring an explicit
    prior call to select_tenant(). Re-checks a cached selection against the
    current permitted set every time, not just at selection time — a
    restriction added mid-session must take effect on the very next query,
    not silently be ignored because a selection was already cached.
    _permitted_tenants and the cached-selection lookup are independent reads,
    gathered concurrently rather than awaited back to back."""
    pool = await get_pool()
    permitted, row = await asyncio.gather(
        _permitted_tenants(staff_identity),
        pool.fetchrow(
            "SELECT selected_hub_id FROM live_session_selection WHERE session_id = $1",
            session_key,
        ),
    )
    if not permitted:
        logger.warning("live_session.no_permitted_tenants", staff=staff_identity)
        await record_audit("live_no_permitted_tenants", staff_identity=staff_identity, detail={})
        raise NoPermittedTenants(f"{staff_identity} has no permitted tenants")

    if row and row["selected_hub_id"]:
        selected_hub_id = row["selected_hub_id"]
        if selected_hub_id not in _hub_ids(permitted):
            await _deny_tenant_access(staff_identity, selected_hub_id, "restricted_mid_session")
        return selected_hub_id

    if len(permitted) == 1:
        only_hub_id = permitted[0]["hub_id"]
        await _persist_tenant_selection(staff_identity, session_key, only_hub_id)
        return only_hub_id

    raise TenantSelectionRequired(
        "More than one tenant is permitted; call select_tenant first"
    )


async def select_tenant_internal(staff_identity: str, session_key: str, hub_id: str) -> None:
    permitted = await _permitted_tenants(staff_identity)
    if hub_id not in _hub_ids(permitted):
        await _deny_tenant_access(staff_identity, hub_id, "explicit_selection_not_permitted")

    await _persist_tenant_selection(staff_identity, session_key, hub_id)


async def _audit(staff_identity: str, hub_id: str, event_type: str, detail: dict) -> None:
    await record_audit(event_type, hub_id=hub_id, staff_identity=staff_identity, detail=detail)


@mcp.tool
async def list_my_tenants() -> list[dict]:
    """Lists the client tenants this staff member is permitted to query, each
    as {"hub_id": ..., "name": ...}. name is never blank — it falls back
    from a human-curated name to HubSpot's own portal domain to the bare
    hub_id, in that order (see _permitted_tenants)."""
    email, _session_key = await _require_staff_identity()
    tenants = await _permitted_tenants(email)
    await _audit(email, None, "live_tenants_listed", {"tenant_count": len(tenants)})
    return tenants


@mcp.tool
async def select_tenant(tenant: str) -> dict:
    """Selects one tenant for this session, by hub_id OR by name (exact
    hub_id match is tried first and always wins — it's unambiguous by
    construction). A name is matched case-insensitively as a substring
    against each permitted tenant's display name. Required when more than
    one tenant is permitted; not needed if only one tenant is permitted.

    If the name matches more than one permitted tenant, this does NOT
    guess: it returns {"ambiguous": True, "candidates": [...]} instead of
    selecting anything, since a wrong guess here is a real cross-tenant
    risk under this project's default-open access model. Call this again
    with one candidate's exact hub_id or full name once you know which one
    is meant."""
    email, session_key = await _require_staff_identity()
    permitted = await _permitted_tenants(email)

    exact_hub = next((t for t in permitted if t["hub_id"] == tenant), None)
    if exact_hub is not None:
        await select_tenant_internal(email, session_key, exact_hub["hub_id"])
        await _audit(email, exact_hub["hub_id"], "live_tenant_selected", {})
        return {"selected_hub_id": exact_hub["hub_id"], "name": exact_hub["name"]}

    needle = tenant.strip().lower()
    name_matches = [t for t in permitted if needle in t["name"].lower()]

    if len(name_matches) == 1:
        match = name_matches[0]
        await select_tenant_internal(email, session_key, match["hub_id"])
        await _audit(email, match["hub_id"], "live_tenant_selected", {})
        return {"selected_hub_id": match["hub_id"], "name": match["name"]}

    if len(name_matches) > 1:
        logger.warning("live_session.tenant_selection_ambiguous", staff=email, query=tenant)
        await _audit(email, None, "live_tenant_selection_ambiguous", {"query": tenant})
        return {
            "ambiguous": True,
            "query": tenant,
            "candidates": [{"hub_id": t["hub_id"], "name": t["name"]} for t in name_matches],
        }

    await _deny_tenant_access(email, tenant, "no_match")


def _category_object_types(category: str) -> set[str]:
    return {t for t, c in OBJECT_TYPE_CATEGORIES.items() if c == category}


async def _query_category(category: str, object_type: str, properties: list[str] | None = None) -> dict:
    """Shared implementation behind the four category-scoped tools below
    (openspec/changes/separate-vertical-client-agents, task 6.1/6.2/6.3 —
    replaces the single generic query_hubspot_data). Matches against all
    three of sync/hubspot_client.py's read paths, not just its generic
    per-object tools: the core CRM object set (contacts, deals, companies,
    etc.) has no per-object tool at all and is only reachable via
    query_crm_data/CRM_OBJECT_TYPES, and campaign metrics always need
    pull_campaign_data()'s per-campaign-ID handling rather than a bare call
    to read_campaign_data (which requires an ID this tool never has).

    CRM object types and CAMPAIGN are strictly gated by category — a real
    object type that exists but belongs to a different category tool is
    rejected explicitly with an {"error": ...} result, not silently
    returned empty, so a caller learns to call the right tool instead of
    assuming no data exists at all. Generic tools are gated the same way,
    via CATEGORY_GENERIC_TOOLS above.

    properties (task 6.3): an optional explicit column list, forwarded to
    pull_crm_objects for every matched CRM object type — this is what lets
    a category tool be scoped to a client's own confirmed-relevant or
    custom fields (from its onboarding profile/client agent instance),
    rather than always returning HubSpot's small default property set.
    Omitting it keeps today's default behavior unchanged."""
    email, session_key = await _require_staff_identity()
    hub_id = await _resolve_selected_tenant(email, session_key)

    client = HubSpotDataPullClient(hub_id)
    lowered = object_type.lower()
    result: dict = {}

    category_types = _category_object_types(category)
    # resolve_object_type_aliases handles irregular plurals/compound names
    # a bare substring check misses ("companies" vs "COMPANY", "landing
    # pages" vs "LANDING_PAGE") — shared with debug_api.py's own resolver.
    all_matching_types = resolve_object_type_aliases(lowered)
    in_category_types = [t for t in all_matching_types if t in category_types]

    if all_matching_types and not in_category_types:
        await _audit(email, hub_id, "live_query_wrong_category", {"object_type": object_type, "category": category})
        return {"error": f"{object_type!r} is not in this tool's category; call the matching category tool instead"}

    # One shared connection for the whole query, mirroring pull_all()'s own
    # connection-reuse — a single interactive query can otherwise trigger
    # a CRM-type call, a campaign lookup, several per-campaign metric
    # calls, and a tool-discovery call, each opening its own connection.
    # Deferred until after the wrong-category check above, so a rejected
    # request never pays for a vault lookup and connection it's about to
    # discard (openspec/changes/codebase-cleanup-and-dedup, task 7).
    http_client, headers = await client._client_for_hub()

    async with http_client:
        if in_category_types:
            properties_map = {t: properties for t in in_category_types} if properties else None
            result.update(
                await client.pull_crm_objects(
                    client=http_client, headers=headers, object_types=in_category_types, properties=properties_map
                )
            )

        if category == CATEGORY_MARKETING_CONTENT and lowered in CRM_OBJECT_ALIASES["CAMPAIGN"]:
            result["campaign_data"] = await client.pull_campaign_data(client=http_client, headers=headers)

        # "team"/"teams" has no CRM_OBJECT_TYPES entry — its only real path
        # is the organization_details capability, matched here via the same
        # organization-means-teams translation hubspot_client.py's own
        # generic-capability categorization already relies on for the
        # scheduled pull.
        query_term = GENERIC_TOOL_QUERY_ALIASES.get(lowered, lowered)
        category_generic_tools = CATEGORY_GENERIC_TOOLS.get(category, set())
        tools = await client.list_read_only_tools(client=http_client)
        matching_tools = [t for t in tools if t in category_generic_tools and query_term in t.lower()]

        async def _pull_tool(tool_name: str) -> tuple[str, object]:
            try:
                return tool_name, await client.pull_object(tool_name, client=http_client, headers=headers)
            except Exception as exc:
                client.log_pull_failure(tool_name, exc)
                return tool_name, {"error": "pull_failed"}

        tool_pairs = await asyncio.gather(*(_pull_tool(t) for t in matching_tools))
        result.update(dict(tool_pairs))

    await _audit(email, hub_id, "live_query", {"object_type": object_type, "category": category})
    logger.info("live_session.query", staff=email, hub_id=hub_id, object_type=object_type, category=category)
    return result


@mcp.tool
async def query_crm_records(object_type: str, properties: list[str] | None = None) -> dict:
    """Returns read-only HubSpot CRM record data for the session's selected
    tenant: 'contacts', 'companies', 'deals', 'tickets', 'line_items', or
    'products'. Optionally pass `properties` (a list of exact HubSpot
    internal property names, including custom/portal-specific ones) to
    return exactly those fields instead of HubSpot's own default set —
    confirmed live this narrows the response rather than adding to it; omit
    it to get just the default set."""
    return await _query_category(CATEGORY_CRM_RECORDS, object_type, properties)


@mcp.tool
async def query_engagement_records(object_type: str, properties: list[str] | None = None) -> dict:
    """Returns read-only HubSpot engagement/activity data for the session's
    selected tenant: 'calls', 'emails', 'meetings', 'notes', or 'tasks'.
    Optionally pass `properties` (exact HubSpot internal property names,
    including custom ones) to return exactly those fields instead of
    HubSpot's own default set."""
    return await _query_category(CATEGORY_ENGAGEMENT_RECORDS, object_type, properties)


@mcp.tool
async def query_marketing_content(object_type: str, properties: list[str] | None = None) -> dict:
    """Returns read-only HubSpot marketing/content data for the session's
    selected tenant: 'campaign', 'landing_pages', 'blog_posts', or 'lists'
    (segments), plus content/campaign analytics tools where applicable.
    Optionally pass `properties` to return exactly those fields instead of
    HubSpot's own default set, for CRM-backed object types."""
    return await _query_category(CATEGORY_MARKETING_CONTENT, object_type, properties)


@mcp.tool
async def query_users(object_type: str, properties: list[str] | None = None) -> dict:
    """Returns read-only HubSpot user/team data for the session's selected
    tenant: 'users', 'owners', or 'teams' (organization-wide team/seat/role
    info). Optionally pass `properties` to return exactly those fields
    instead of HubSpot's own default set, for the 'users' object type."""
    return await _query_category(CATEGORY_USERS, object_type, properties)


# Prompts return static instruction text only — they never touch the vault,
# Postgres, or HubSpot themselves. All real data access still goes through
# select_tenant/the four category-scoped query_* tools above, so nothing here needs its own
# staff-identity or tenant-permission check; a prompt can't leak anything a
# tool call wouldn't already guard. A first, deliberately small pair, not a
# full library — real staff usage (none exists yet, since no client is
# onboarded beyond Blu Mountain's own test portals) should drive what's
# added next, not a guess at what might be wanted.
#
# Return type is a bare str, not list[Message]/list[dict] as this pinned
# FastMCP version's own @mcp.prompt docstring example shows — confirmed
# live that a dict message raises PromptError at render time on this
# version ("messages[0] must be Message or str, got dict"); a bare string
# is what actually works.


@mcp.prompt
def tenant_pipeline_overview(tenant: str) -> str:
    """Summarizes one tenant's open sales pipeline: select the tenant, pull
    its deals and companies, and report deal count, total value, and which
    companies have the most active deals."""
    return (
        f"Select the tenant '{tenant}' (call select_tenant; if the result "
        "is ambiguous, ask me which candidate is meant rather than "
        "guessing). Then call query_crm_records for 'deals' and "
        "'companies'. Summarize the open pipeline: how many deals are "
        "open, their total value if the amount field is populated, and "
        "which companies have the most active deals."
    )


@mcp.prompt
def tenant_recent_activity(tenant: str) -> str:
    """Summarizes one tenant's recent engagement: select the tenant, pull
    its calls, emails, and meetings, and report a short activity digest."""
    return (
        f"Select the tenant '{tenant}' (call select_tenant; if the result "
        "is ambiguous, ask me which candidate is meant rather than "
        "guessing). Then call query_engagement_records for 'calls', "
        "'emails', and 'meetings'. Summarize recent activity: roughly how "
        "much of each kind happened, and anything notable worth flagging."
    )
