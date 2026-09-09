"""Client agent for hub_id 149094230 ("Blu Mountain - Test Account", the
Enterprise/Marketing-Hub-Pro-equivalent HubSpot developer test portal,
with a real "Transaction" custom object). Migrated from the prior
client_agent_instances row (produced 2026-09-01), which had zero
confirmed-relevant fields and — incorrectly — pointed at the saas
template; the tenant's real vertical is marketplace, corrected directly
in the database as part of this change (openspec/changes/
client-vertical-agent-classes)."""

from ..registry import register_client_agent
from ..verticals.marketplace import MarketplaceAgent


@register_client_agent("149094230")
class BluMountainTestAccountAgent(MarketplaceAgent):
    HUB_ID = "149094230"

    # Nothing confirmed yet, deliberately: setting any entry here narrows
    # that object type's tool request to *only* the listed fields — it
    # stops falling back to full discovery for that type (see
    # context/CLIENT_AGENT_CLASSES.md). Leaving this empty means the
    # agent currently sees every real field on every object type,
    # including custom ones (take_rate, etc.) — the safer default until
    # a human deliberately trades that breadth for a narrower, curated
    # set. This tenant's real custom "Transaction" object (objectTypeId
    # 2-252820399, confirmed live via list_custom_objects) has no
    # confirmed fields yet either — add an entry keyed by that
    # objectTypeId once one is decided on.
    #
    # For a current, real candidate list — standard object types AND this
    # tenant's own custom objects (not a static snapshot that goes stale
    # the moment a portal field changes): run
    #   docker exec -w /app mcp-gateway python3 generate_confirmed_fields.py 149094230
    # (see gateway/scripts/generate_confirmed_fields.py) — it separates
    # populated fields into framework-trusted, framework-flagged-
    # unreliable (excluded on purpose), and needs-a-human-decision.
    CONFIRMED_FIELDS: dict[str, list[str]] = {}
