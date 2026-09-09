# Client Agent Classes Runbook

Covers how to create, edit, and save a **client's** agent — one of the classes under `gateway/frameworks/agents/clients/`, each subclassing its vertical's class. See `context/VERTICAL_AGENT_CLASSES.md` for the vertical-level equivalent, and `openspec/changes/client-vertical-agent-classes/design.md` for the full reasoning.

There is no admin UI. "Saving" a client's agent means committing a Python file and deploying — the same tradeoff described in the vertical runbook.

## What a client class is

One file per client under `gateway/frameworks/agents/clients/`, e.g. `blu_mountain_gumpper.py`:

```python
from ..registry import register_client_agent
from ..verticals.saas import SaaSAgent

@register_client_agent("148997330")
class BluMountainGumpperAgent(SaaSAgent):
    HUB_ID = "148997330"
    CONFIRMED_FIELDS: dict[str, list[str]] = {
        "CONTACT": ["health_score", "plan_tier"],
    }
```

Three things happen here:

- **Subclass the right vertical.** `BluMountainGumpperAgent(SaaSAgent)` means this client inherits the SaaS vertical's framework text and `SYSTEM_PROMPT_ADDITIONS` — identical to every other SaaS client. Get this wrong (subclassing the wrong vertical) and the client's agent reasons about the wrong business model; there's no runtime check that catches a mismatch, only whatever a human notices in the gathered data.
- **Set `HUB_ID`.** The one tenant this class is allowed to touch. `BaseAgent.__init__` refuses to construct without it.
- **Set `CONFIRMED_FIELDS`.** This is "for this client, use these fields" — the mechanism this whole class-based system exists to make real code instead of a database read. See below.

`@register_client_agent("148997330")` is what makes `run_client_agent("148997330")` findable at all — a class that exists but isn't decorated (or is decorated with the wrong hub_id) never runs; `run_client_agent` raises a clear `ValueError` naming the hub_id instead of silently doing nothing.

## Setting which fields a client's agent looks at

`CONFIRMED_FIELDS` is `{object_type_or_custom_object_type_id: [property_name, ...]}`.

- **Standard HubSpot object**: key by the same name the tool surface already uses — `"CONTACT"`, `"COMPANY"`, `"DEAL"`, etc. (the full list is `sync.hubspot_client.CRM_OBJECT_TYPES`).
- **Custom object**: key by its real, discovered `objectTypeId` (a string like `"2-252820399"`), not a friendly name — there isn't one. Discover it first by actually running the agent and checking what `list_custom_objects` returns for that tenant (or via the debug API's `GET /debug/hubspot/{hub_id}/custom-objects`), then hardcode the `objectTypeId` you found into this file.

**What setting a field does**: when the agent's `pull_object_type` (or `pull_custom_object`) tool runs for an object type with an entry here, it requests *exactly* those fields from HubSpot — nothing broader, even if HubSpot has other real properties on that object. **What leaving an object type out does**: the agent falls back to full live discovery for that object type, requesting every real property (standard and custom) HubSpot returns — this is today's behavior for every client that hasn't been curated yet, and it's not a broken or degraded state, just an uncurated one.

**This takes effect on the next run, automatically — no re-registration, no other step.** `CONFIRMED_FIELDS` is read live off the class every time the agent runs; there's no snapshot to refresh or instance to re-produce. Edit the file, rebuild, redeploy — the very next `run_client_agent(hub_id)` call picks it up.

**"Until we specifically request different fields"**: to change what's confirmed, edit the list directly in this file. There's no separate "unconfirm" step distinct from just changing what the list contains — the list *is* the current state, not an audit trail of changes. Git history is the change log.

## Create a new client's agent

1. Confirm the tenant is actually installed (`tenants` table, `install_status = 'installed'`) and know its real vertical — a human decision, check with whoever onboarded the client; don't assume from the tenant's name or industry guess. There's no database column to check instead (see `VERTICAL_AGENT_CLASSES.md`) — a client's vertical is only ever known by which vertical class its agent subclasses, so for an existing client, read its own file.
2. Create `gateway/frameworks/agents/clients/<client_slug>.py`:
   ```python
   from ..registry import register_client_agent
   from ..verticals.<vertical_module> import <VerticalName>Agent

   @register_client_agent("<hub_id>")
   class <ClientName>Agent(<VerticalName>Agent):
       HUB_ID = "<hub_id>"
       CONFIRMED_FIELDS: dict[str, list[str]] = {}
   ```
   Starting with an empty `CONFIRMED_FIELDS` is correct and normal — it just means full discovery for every object type until a human curates something, same as every client starts today.
3. Add it to `gateway/frameworks/agents/clients/__init__.py`'s imports — this is what actually makes the registration run; a file that exists but is never imported never registers.
4. Rebuild and redeploy.
5. Confirm it's real: `run_client_agent("<hub_id>")` should no longer raise, and `frameworks.agents.registry.get_registered_agent_class("<hub_id>")` should return the new class.

## What you cannot do here

- You cannot give a client its own `SYSTEM_PROMPT_ADDITIONS` distinct from its vertical's — deliberately not built (see `VERTICAL_AGENT_CLASSES.md` and `design.md`'s resolved decision). A client's file only ever adds fields/objects, never behavioral instructions. If a real client ever needs genuinely different *behavior*, not just different *fields*, that's a design decision to revisit deliberately, not something to route around by, e.g., stuffing instructions into `CONFIRMED_FIELDS`.
- You cannot register two different classes under the same `hub_id` — `@register_client_agent` raises `DuplicateClientRegistration` immediately if you try, rather than silently letting the second registration win.
