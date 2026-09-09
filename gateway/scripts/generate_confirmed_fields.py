"""One-time/on-demand generator: proposes a CONFIRMED_FIELDS dict for one
registered client agent from real, live profiling data, instead of a human
reading raw HubSpot properties cold.

Never writes to a client's file directly — a human still reviews and pastes
the result in, matching this project's standing "no automatic behavior
change without a human decision" posture (the removed onboarding-profile
pipeline's own human-review checkpoint lives on here in spirit;
CONFIRMED_FIELDS's own git-history-as-audit-trail design,
context/CLIENT_AGENT_CLASSES.md). This only reads:
frameworks.profiling.profile_tenant_fields() (standard object types) and
HubSpotDataPullClient.discover_custom_object_schemas() (this tenant's own
custom objects, if any — added 2026-09-08) — the same, already-allowlisted
read paths everything else in this project pulls HubSpot data through, no
new HubSpot access path.

Proposal logic, per object type, for every populated field: a field with
trust_by_default guidance from the client's own vertical framework is
proposed as confirmed; a field with unreliable_by_default guidance is
deliberately excluded and listed separately, so it's not silently
forgotten; a field with no guidance either way prints as a needs_review
candidate — exactly the same shape as the comments already sitting in every
client file today, a human decision, never auto-included. A custom
object's fields always land in needs_review — Blu Mountain's generic
vertical frameworks have no guidance for a field that's specific to one
client's own portal by definition.

The client's vertical comes from its own registered agent class
(agents/registry.py), not the `tenants.vertical` database column — the
class is the authoritative source of truth as of the class-based agent
migration, and the column has drifted from it before (149094230 was once
wrongly "saas" in the database).

Run from inside the mcp-gateway container (needs the real vaulted HubSpot
token for hub_id, already configured for the dev stack):

    docker compose up -d
    docker cp gateway/scripts/generate_confirmed_fields.py mcp-gateway:/app/generate_confirmed_fields.py
    docker exec -w /app mcp-gateway python3 generate_confirmed_fields.py <hub_id>
"""

import asyncio
import sys

from frameworks.agents import clients as _client_agents  # noqa: F401 — registers every real client
from frameworks.agents.registry import get_registered_agent_class
from frameworks.profiling import profile_tenant_fields
from sync.hubspot_client import CRM_OBJECT_TYPES, HubSpotDataPullClient


async def _generate(hub_id: str) -> None:
    agent_class = get_registered_agent_class(hub_id)
    vertical = agent_class.VERTICAL
    print(f"Profiling hub_id={hub_id!r} ({agent_class.__name__}, vertical={vertical!r})...")

    client = HubSpotDataPullClient(hub_id)
    custom_schemas = await client.discover_custom_object_schemas()
    custom_object_type_ids = [s["objectTypeId"] for s in custom_schemas]
    if custom_schemas:
        print(f"Found {len(custom_schemas)} real custom object schema(s): ", end="")
        print(", ".join(f"{s['objectTypeId']} ({s.get('name')})" for s in custom_schemas))

    profiled = await profile_tenant_fields(
        hub_id, object_types=CRM_OBJECT_TYPES, vertical=vertical, custom_object_type_ids=custom_object_type_ids
    )

    confirmed: dict[str, list[str]] = {}
    needs_review: dict[str, list[str]] = {}
    excluded_unreliable: dict[str, list[str]] = {}

    for object_type, field_profiles in profiled.items():
        for fp in field_profiles:
            if not fp.populated:
                continue
            if fp.framework_guidance == "trust_by_default":
                confirmed.setdefault(object_type, []).append(fp.name)
            elif fp.framework_guidance == "unreliable_by_default":
                excluded_unreliable.setdefault(object_type, []).append(fp.name)
            else:
                needs_review.setdefault(object_type, []).append(fp.name)

    print()
    print("=" * 78)
    print(f"Proposed CONFIRMED_FIELDS for {hub_id!r} — review before pasting into")
    print(f"gateway/frameworks/agents/clients/<{agent_class.__module__.rsplit('.', 1)[-1]}>.py")
    print("=" * 78)
    print("CONFIRMED_FIELDS: dict[str, list[str]] = {")
    for object_type in sorted(confirmed):
        fields = ", ".join(repr(f) for f in sorted(confirmed[object_type]))
        print(f'    "{object_type}": [{fields}],')
    print("}")

    if excluded_unreliable:
        print()
        print("# Populated but framework-flagged unreliable_by_default — deliberately")
        print("# excluded above, listed here so they're not silently forgotten:")
        for object_type in sorted(excluded_unreliable):
            fields = ", ".join(sorted(excluded_unreliable[object_type]))
            print(f"# {object_type}: {fields}")

    if needs_review:
        print()
        print("# Populated, no framework guidance either way — needs a human decision,")
        print("# move a name into CONFIRMED_FIELDS above once one is made:")
        for object_type in sorted(needs_review):
            fields = ", ".join(sorted(needs_review[object_type]))
            print(f"# {object_type}: {fields}")

    if not confirmed and not needs_review and not excluded_unreliable:
        print("(nothing populated at all for any profiled object type)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python3 generate_confirmed_fields.py <hub_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(_generate(sys.argv[1]))
