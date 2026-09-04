"""One agent class per client (openspec/changes/client-vertical-agent-classes),
each subclassing its vertical's class and self-registering via
@register_client_agent on import. Importing this package is what makes
every client's class actually reachable through the registry — a new
client is purely an additive new module here, imported below."""

from . import blu_mountain_gumpper, blu_mountain_test_account  # noqa: F401
