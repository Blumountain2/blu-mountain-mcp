"""Public surface of the session subsystem: the live interactive session
(FastMCP's OAuth Proxy over Google Workspace, reachable identically from
Claude Desktop, Claude Code, or Claude Cowork).

`staff_auth.py` also lives in this package (direct Google/Microsoft staff
JWT verification) but is not re-exported here: `main.py` no longer wires it
in. It's kept, unhooked, in case a future non-MCP consumer needs it, import
it directly as `session.staff_auth` if so.

Named `session`, not `mcp`: this package sits alongside `fastmcp`, which
depends on the real `mcp` SDK package (imported internally as `mcp.types`
etc.). A local subpackage literally named `mcp` would shadow that real
dependency on sys.path and break fastmcp's own imports."""

from .live_session import mcp

__all__ = [
    "mcp",
]
