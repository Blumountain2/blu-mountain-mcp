"""Client agent instances (openspec/changes/separate-vertical-client-agents):
one persisted, independently-editable agent instance per client, built from
that client's vertical's current agent template plus that client's own
injected documentation (onboarding-profile fields, confirmed custom
fields, any client-specific notes).

This is a deliberate, knowing supersession of
`openspec/changes/analysis-model-templates/design.md`'s Non-Negotiable #6
("one agent config per vertical, shared across every client... no
per-client persisted config") — see this change's own `design.md` for the
full reasoning. What's unchanged: still one shared Anthropic API
credential, still one shared deployment; what's new is that a client's
agent behavior is now a durable, versioned row instead of context
re-assembled from scratch on every call.

Isolation is structural, matching `onboarding.py`'s pattern exactly: every
read or write here takes `hub_id` and enforces it directly in the query, so
a client agent instance can never be fetched or mutated through another
client's `hub_id`, by construction.
"""

from dataclasses import dataclass

import structlog

from db import get_pool

from ._versioning import next_version
from .onboarding import STATUS_CONFIRMED_RELEVANT, get_latest_profile_for_tenant
from .vertical import resolve_vertical_or_raise
from .vertical_templates import VerticalAgentTemplate, get_latest_template, get_template_by_id

logger = structlog.get_logger()


@dataclass(frozen=True)
class ClientAgentInstance:
    id: int
    hub_id: str
    vertical_template_id: int
    version: int
    injected_documentation: str


def _render_injected_documentation(profile) -> str:
    """The per-client half of an agent instance — this is what makes two
    clients of the same vertical genuinely differ, not just the shared
    template. Same rendering shape as the prior ephemeral
    `pull_agent._client_context_block`, now persisted rather than
    recomputed on every run."""
    if profile is None:
        return "No onboarding profile exists yet for this client — no confirmed-relevant fields to prioritize."

    confirmed = [f for f in profile.fields if f.status == STATUS_CONFIRMED_RELEVANT]
    lines = [f"Client: {profile.name}"]
    if confirmed:
        lines.append("Fields already confirmed relevant for this client:")
        for f in confirmed:
            guidance = f" ({f.framework_guidance})" if f.framework_guidance else ""
            lines.append(f"  - {f.object_type}.{f.property_name}{guidance}")
    else:
        lines.append("No fields have been confirmed relevant for this client yet.")
    return "\n".join(lines)


async def produce_client_agent_instance(
    hub_id: str,
    vertical: str | None = None,
    allow_unqualified: bool = False,
) -> int:
    """Produces a new versioned client agent instance for hub_id, built
    from that vertical's current template plus a fresh read of hub_id's
    onboarding profile. Returns the new instance's id.

    A vertical is required, resolved from an explicit argument first,
    then from the tenant's own stored vertical
    (`frameworks.vertical.get_tenant_vertical`). Unlike
    `onboarding.produce_onboarding_profile`, there is no unqualified path
    here: `client_agent_instances.vertical_template_id` is NOT NULL, so an
    instance can never be produced without a resolved vertical.
    `allow_unqualified` is still accepted and forwarded (some callers pass
    it through uniformly alongside onboarding-profile production), but it
    cannot make this function succeed without a vertical — it only
    changes the error into `resolve_vertical_or_raise`'s own refusal
    message instead of this function's.

    Refuses if the resolved vertical has no vertical_agent_templates row
    yet — a client instance can't be built from a template that doesn't
    exist, and producing one from raw analysis_content alone would defeat
    the point of an independently-editable vertical template."""
    vertical = await resolve_vertical_or_raise(
        hub_id, vertical, allow_unqualified, purpose="which agent template this client's instance is built from"
    )
    if vertical is None:
        raise ValueError(
            f"Tenant {hub_id!r} has no vertical selected. A client agent instance always requires one — "
            "set one first via frameworks.vertical.set_tenant_vertical(hub_id, vertical). "
            "allow_unqualified=True does not apply here: unlike an onboarding profile, an instance "
            "can never be produced without a resolved vertical (client_agent_instances.vertical_template_id "
            "is NOT NULL)."
        )

    # vertical is guaranteed non-None past this point (the check above
    # raises otherwise), so this always runs — no "unqualified" path
    # exists for this function's own template lookup.
    template: VerticalAgentTemplate = await get_latest_template(vertical)
    if template is None:
        raise ValueError(
            f"No vertical agent template exists yet for vertical {vertical!r}. "
            "Ingest one first via frameworks.vertical_templates.ingest_template."
        )

    profile = await get_latest_profile_for_tenant(hub_id)
    injected_documentation = _render_injected_documentation(profile)

    pool = await get_pool()
    new_version = await next_version(pool, "client_agent_instances", "hub_id = $1", hub_id)

    instance_id = await pool.fetchval(
        """
        INSERT INTO client_agent_instances (hub_id, vertical_template_id, version, injected_documentation)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        hub_id,
        template.id,
        new_version,
        injected_documentation,
    )
    logger.info(
        "frameworks.client_agent.instance_produced",
        hub_id=hub_id,
        instance_id=instance_id,
        vertical=vertical,
        vertical_template_version=template.version,
    )
    return instance_id


async def get_latest_client_agent_instance(hub_id: str) -> ClientAgentInstance | None:
    """Returns hub_id's current (latest) client agent instance, or None if
    none has been produced yet. Scoped by hub_id directly in the query —
    the same structural isolation as `onboarding.get_latest_profile_for_tenant`."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, hub_id, vertical_template_id, version, injected_documentation "
        "FROM client_agent_instances WHERE hub_id = $1 ORDER BY version DESC LIMIT 1",
        hub_id,
    )
    return ClientAgentInstance(**dict(row)) if row is not None else None


async def get_instance_for_tenant(hub_id: str, instance_id: int) -> ClientAgentInstance | None:
    """Returns the instance only if it was actually produced for hub_id —
    structural enforcement, not just convention, matching
    `onboarding.get_profile_for_tenant`'s pattern: a wrong hub_id returns
    None indistinguishably from "doesn't exist," never another tenant's
    instance."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, hub_id, vertical_template_id, version, injected_documentation "
        "FROM client_agent_instances WHERE id = $1 AND hub_id = $2",
        instance_id,
        hub_id,
    )
    return ClientAgentInstance(**dict(row)) if row is not None else None


async def resolve_client_agent_instance(
    hub_id: str,
    vertical: str | None = None,
    allow_unqualified: bool = False,
) -> ClientAgentInstance:
    """Returns hub_id's current client agent instance, producing one first
    if none exists yet. This is the entry point `pull_agent.run_client_agent`
    uses — callers never need to know whether an instance already existed."""
    existing = await get_latest_client_agent_instance(hub_id)
    if existing is not None:
        return existing

    instance_id = await produce_client_agent_instance(hub_id, vertical=vertical, allow_unqualified=allow_unqualified)
    produced = await get_instance_for_tenant(hub_id, instance_id)
    assert produced is not None  # just inserted under the same hub_id
    return produced


async def resolve_template_for_instance(instance: ClientAgentInstance) -> VerticalAgentTemplate:
    """Resolves the exact vertical agent template version an instance was
    built from — never the vertical's current latest, so an in-flight or
    historical instance always reads the same template content it was
    produced against."""
    template = await get_template_by_id(instance.vertical_template_id)
    assert template is not None  # FK-enforced; a referenced template row can't disappear
    return template
