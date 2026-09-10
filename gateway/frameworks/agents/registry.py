"""hub_id -> client agent class lookup (openspec/changes/client-vertical-agent-classes).

A self-registering decorator, not one hand-maintained dict every client
onboarding would have to edit — at ~50+ expected clients, a shared dict
literal is a growing merge-conflict hotspot; a decorator sitting right
next to the class it registers keeps onboarding purely additive (a new
file, no other file touched)."""

from .base import BaseAgent

_REGISTRY: dict[str, type[BaseAgent]] = {}


class DuplicateClientRegistration(Exception):
    """Raised when two classes are registered under the same hub_id — a
    real authoring mistake, never silently resolved by last-registration-wins."""


def register_client_agent(hub_id: str):
    """Class decorator: `@register_client_agent("148997330")` above a
    client's agent class registers it under that hub_id."""

    def _decorator(cls: type[BaseAgent]) -> type[BaseAgent]:
        existing = _REGISTRY.get(hub_id)
        if existing is not None and existing is not cls:
            raise DuplicateClientRegistration(
                f"hub_id {hub_id!r} is already registered to {existing.__name__}, "
                f"cannot also register {cls.__name__}"
            )
        _REGISTRY[hub_id] = cls
        return cls

    return _decorator


def get_registered_agent_class(hub_id: str) -> type[BaseAgent]:
    """Returns the registered client agent class for hub_id, or raises a
    clear error naming it — never silently falls back to a generic or
    default agent for a tenant with no authored class yet."""
    cls = _REGISTRY.get(hub_id)
    if cls is None:
        raise ValueError(
            f"No client agent class registered for hub_id {hub_id!r}. "
            "Author one under gateway/frameworks/agents/clients/ and register it "
            "with @register_client_agent before running this tenant's agent."
        )
    return cls


def registered_hub_ids() -> frozenset[str]:
    return frozenset(_REGISTRY.keys())


def vertical_for_hub_id(hub_id: str) -> str | None:
    """Returns the registered client agent class's vertical for hub_id, or
    None if hub_id has no registered class yet — a tenant can be installed
    and permitted for a staff member's session without an agent class
    having been authored for it yet, so callers (e.g. the live session's
    tenant-listing tool) must not treat this as an error."""
    cls = _REGISTRY.get(hub_id)
    return cls.VERTICAL if cls is not None else None
