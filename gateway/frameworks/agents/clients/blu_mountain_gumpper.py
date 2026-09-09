"""Client agent for hub_id 148997330 ("Blu Mountain & Gumpper", the
baseline-tier HubSpot developer test portal). Migrated from the prior
client_agent_instances row (produced 2026-09-01), which had zero
confirmed-relevant fields — there was nothing real to carry over, only
the tenant identity and vertical assignment (openspec/changes/
client-vertical-agent-classes)."""

from ..registry import register_client_agent
from ..verticals.saas import SaaSAgent


@register_client_agent("148997330")
class BluMountainGumpperAgent(SaaSAgent):
    HUB_ID = "148997330"

    # Nothing confirmed yet, deliberately: setting any entry here narrows
    # that object type's tool request to *only* the listed fields — it
    # stops falling back to full discovery for that type (see
    # context/CLIENT_AGENT_CLASSES.md). Leaving this empty means the
    # agent currently sees every real field on every object type,
    # including custom ones (health_score, plan_tier, jobtitle, etc.) —
    # the safer default until a human deliberately trades that breadth
    # for a narrower, curated set.
    #
    # For a current, real candidate list (not a static snapshot that
    # goes stale the moment a portal field changes): run
    #   docker exec -w /app mcp-gateway python3 generate_confirmed_fields.py 148997330
    # (see gateway/scripts/generate_confirmed_fields.py) — it separates
    # populated fields into framework-trusted, framework-flagged-
    # unreliable (excluded on purpose), and needs-a-human-decision.
    CONFIRMED_FIELDS: dict[str, list[str]] = {}
