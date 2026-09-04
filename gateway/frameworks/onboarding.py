"""Tenant onboarding profiles (task 3, specs/tenant-template-instantiation
/spec.md): a lightweight, named, per-tenant record of which fields are
confirmed relevant for that tenant's analysis — a runtime parameter to
hand to a vertical framework at invocation time, never a copy of the
framework/skill/prompt itself (design.md's corrected decision: one
shared, unmodified framework, parameterized per client at runtime, not a
persisted per-client copy of the framework).

Isolation is structural, not just conventional: every read or write here
takes hub_id and enforces it directly in the query (a JOIN/WHERE clause,
not a python-level check that a caller could accidentally skip) — a
profile belonging to one tenant simply cannot be fetched or mutated
through another tenant's hub_id, by construction.
"""

from dataclasses import dataclass

import structlog

from auth import TENANT_DISPLAY_NAME_SQL
from db import get_pool

from .profiling import profile_tenant_fields
from .vertical import resolve_vertical_or_raise

logger = structlog.get_logger()

STATUS_CONFIRMED_RELEVANT = "confirmed_relevant"
STATUS_CONFIRMED_IRRELEVANT = "confirmed_irrelevant"
STATUS_NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class OnboardingProfileField:
    object_type: str
    property_name: str
    status: str
    framework_guidance: str | None


@dataclass(frozen=True)
class OnboardingProfile:
    id: int
    hub_id: str
    name: str
    vertical: str | None
    fields: list[OnboardingProfileField]

    @property
    def is_final(self) -> bool:
        """A profile is final only once every field has moved past
        needs_review — the human-review checkpoint
        (specs/tenant-template-instantiation/spec.md)."""
        return all(f.status != STATUS_NEEDS_REVIEW for f in self.fields)


async def _effective_tenant_name(hub_id: str) -> str:
    """Same resolution order already used for the live session and the
    debug API (`auth.token_vault.TENANT_DISPLAY_NAME_SQL`): portal_name ->
    hub_domain -> hub_id, blank values treated as absent."""
    pool = await get_pool()
    row = await pool.fetchrow(
        f"SELECT {TENANT_DISPLAY_NAME_SQL} AS name FROM tenants WHERE hub_id = $1",
        hub_id,
    )
    if row is None:
        raise ValueError(f"Unknown tenant: {hub_id!r}")
    return row["name"]


async def produce_onboarding_profile(
    hub_id: str,
    object_types: list[str],
    vertical: str | None = None,
    allow_unqualified: bool = False,
) -> int:
    """Profiles hub_id's real HubSpot fields (via frameworks.profiling —
    no new HubSpot access path) and produces a named, tenant-scoped
    onboarding profile from the result. Only populated fields become
    candidates. A field the tenant's known framework already has
    explicit guidance for (trust_by_default or unreliable_by_default —
    either means the framework actively discussed this field) is
    auto-confirmed relevant, carrying that guidance; a populated field
    with no framework guidance is marked needs_review. Returns the new
    profile's id.

    A vertical is required by default (2026-08-31) — it's what determines
    how this client's data gets interpreted, and a profile produced
    without one carries no framework guidance at all, every field lands
    in needs_review. If `vertical` isn't passed explicitly, this resolves
    the tenant's own known vertical from Postgres
    (frameworks.vertical.get_tenant_vertical) rather than silently
    proceeding unqualified. If neither source has one, this refuses with
    a clear, actionable message rather than a quiet, worse-quality
    result — the closest a backend function gets to "prompting" a human
    caller, since there's no interactive interface at this call site.
    Pass allow_unqualified=True to proceed anyway — an explicit,
    deliberate choice, never an accidental default."""
    vertical = await resolve_vertical_or_raise(
        hub_id, vertical, allow_unqualified, purpose="how this client's data is interpreted"
    )

    name = await _effective_tenant_name(hub_id)
    profiled = await profile_tenant_fields(hub_id, object_types=object_types, vertical=vertical)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            profile_id = await conn.fetchval(
                "INSERT INTO tenant_onboarding_profiles (hub_id, name, vertical) VALUES ($1, $2, $3) RETURNING id",
                hub_id,
                name,
                vertical,
            )
            # One batched insert instead of one round trip per populated
            # field — a tenant can have hundreds of real properties across
            # its object types (CLAUDE.md: "hundreds of fields, including
            # custom ones" for a single object type alone).
            field_rows = [
                (
                    profile_id,
                    object_type,
                    fp.name,
                    STATUS_CONFIRMED_RELEVANT if fp.framework_guidance is not None else STATUS_NEEDS_REVIEW,
                    fp.framework_guidance,
                )
                for object_type, field_profiles in profiled.items()
                for fp in field_profiles
                if fp.populated
            ]
            if field_rows:
                await conn.executemany(
                    """
                    INSERT INTO tenant_onboarding_profile_fields
                        (profile_id, object_type, property_name, status, framework_guidance)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    field_rows,
                )

    logger.info(
        "frameworks.onboarding.profile_produced",
        hub_id=hub_id,
        profile_id=profile_id,
        name=name,
        vertical=vertical,
    )
    return profile_id


async def _load_profile(pool, profile_row) -> OnboardingProfile:
    """Shared by get_profile_for_tenant/get_latest_profile_for_tenant below —
    both need the identical "load this profile row's fields, build an
    OnboardingProfile" step once they've each found their own profile_row
    via a different, isolation-scoped query."""
    field_rows = await pool.fetch(
        "SELECT object_type, property_name, status, framework_guidance "
        "FROM tenant_onboarding_profile_fields WHERE profile_id = $1 "
        "ORDER BY object_type, property_name",
        profile_row["id"],
    )
    fields = [OnboardingProfileField(**dict(row)) for row in field_rows]
    return OnboardingProfile(**dict(profile_row), fields=fields)


async def get_profile_for_tenant(hub_id: str, profile_id: int) -> OnboardingProfile | None:
    """Returns the profile only if it was actually produced for hub_id —
    structural enforcement of "an onboarding profile is usable only for
    the tenant it was produced for," not just a documented convention a
    caller could accidentally violate. Returns None both when the
    profile doesn't exist at all and when it exists but belongs to a
    different tenant — deliberately indistinguishable to a caller, so a
    wrong hub_id can never be used to probe for another tenant's
    profile's existence."""
    pool = await get_pool()
    profile_row = await pool.fetchrow(
        "SELECT id, hub_id, name, vertical FROM tenant_onboarding_profiles WHERE id = $1 AND hub_id = $2",
        profile_id,
        hub_id,
    )
    return await _load_profile(pool, profile_row) if profile_row is not None else None


async def get_latest_profile_for_tenant(hub_id: str) -> OnboardingProfile | None:
    """Returns the most recently produced onboarding profile for hub_id, or
    None if none exists yet. Scoped by hub_id alone, the same structural
    isolation as get_profile_for_tenant — a caller can never retrieve
    another tenant's most-recent profile by construction, not convention.

    Used by the vertical pull agent (task 8, specs/vertical-pull-agent
    /spec.md) to inject a client's own confirmed-relevant fields into its
    request — the piece that makes a run's prompt genuinely per-client,
    not just per-vertical."""
    pool = await get_pool()
    profile_row = await pool.fetchrow(
        "SELECT id, hub_id, name, vertical FROM tenant_onboarding_profiles "
        "WHERE hub_id = $1 ORDER BY created_at DESC LIMIT 1",
        hub_id,
    )
    return await _load_profile(pool, profile_row) if profile_row is not None else None


async def review_field(
    hub_id: str,
    profile_id: int,
    object_type: str,
    property_name: str,
    confirmed_relevant: bool,
    reviewed_by: str,
) -> bool:
    """The human-review checkpoint: moves one field from needs_review to
    confirmed_relevant or confirmed_irrelevant. Scoped by hub_id the same
    way get_profile_for_tenant is (a JOIN enforcing the profile actually
    belongs to hub_id), so a review action can never target a profile
    belonging to a different tenant, structurally. Returns True if a
    field was actually updated, False if no matching row was found
    (wrong tenant, wrong profile, or wrong field)."""
    status = STATUS_CONFIRMED_RELEVANT if confirmed_relevant else STATUS_CONFIRMED_IRRELEVANT
    pool = await get_pool()
    result = await pool.execute(
        """
        UPDATE tenant_onboarding_profile_fields AS f
        SET status = $1, reviewed_by = $2, reviewed_at = now()
        FROM tenant_onboarding_profiles AS p
        WHERE f.profile_id = p.id
          AND p.hub_id = $3
          AND f.profile_id = $4
          AND f.object_type = $5
          AND f.property_name = $6
        """,
        status,
        reviewed_by,
        hub_id,
        profile_id,
        object_type,
        property_name,
    )
    updated = result.split()[-1] != "0"
    if updated:
        logger.info(
            "frameworks.onboarding.field_reviewed",
            hub_id=hub_id,
            profile_id=profile_id,
            object_type=object_type,
            property_name=property_name,
            status=status,
            reviewed_by=reviewed_by,
        )
    return updated
