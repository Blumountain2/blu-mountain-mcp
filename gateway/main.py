"""
HubSpot MCP Server.

Hosts, side by side:
- HubSpot OAuth v3 + PKCE install/callback (Flow B) and the HubSpot
  uninstall webhook (auth.hubspot_oauth, auth.token_vault) — the single
  install step. HubSpotDataPullClient now reads HubSpot's plain REST API
  (api.hubapi.com) using this Public App token directly
  (openspec/changes/hubspot-rest-api-pivot); a second install step is no
  longer needed.
- The scheduled Airtable staging cycle (sync.airtable_staging), driven by
  APScheduler on SYNC_INTERVAL_MINUTES.
- A daily audit-log retention purge (auth.security.purge_expired_audit_log),
  deleting entries older than AUDIT_RETENTION_DAYS.
- The Sybill webhook receiver (webhooks.sybill).
- The live interactive session (session.live_session), FastMCP's OAuth Proxy
  wrapping Google Workspace, mounted at /mcp — reachable identically from
  Claude Desktop, Claude Code, or Claude Cowork.
- A plain HTTP debug API (debug_api) for pulling a real installed tenant's
  HubSpot data via Postman rather than the MCP protocol — gated shut by
  default (DEBUG_API_KEY empty = every request 401s).

Direct Google/Microsoft staff/owner authentication (session.staff_auth) is
not wired in here. It's kept in the codebase, unhooked, in case a non-MCP
consumer (e.g. a future web dashboard) ends up needing it; see design.md's
decision log in the implement-hubspot-mcp-server change for why.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict
from urllib.parse import urlparse

import structlog
from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from auth import (
    hubspot_oauth_router,
    purge_expired_audit_log,
    record_audit_best_effort,
    token_vault_router,
)
from config import settings
from db import close_pool, get_pool, init_schema
from debug_api import router as debug_api_router
from session import mcp as live_mcp
from sync import run_staging_cycle
from webhooks import sybill_router

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


# Holds a strong reference to every in-flight _on_scheduled_job_error audit
# task. asyncio only keeps a weak reference to a task with no other
# referent — an unreferenced task can be garbage-collected mid-execution,
# silently dropping the very audit write this listener exists to
# guarantee (see https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task).
# Each task removes itself once done via add_done_callback below.
_pending_job_error_audits: set[asyncio.Task] = set()


def _on_scheduled_job_error(event: JobExecutionEvent) -> None:
    """Global safety net for every scheduled job, present and future: even
    an exception a job's own code never reaches its own try/except for
    (e.g. a bug in setup code before that job's first `try:` — confirmed
    live as a real gap in run_staging_cycle's tenant-listing step before
    this listener existed) still gets logged and recorded here, rather
    than only reaching APScheduler's own internal logger where it'd be
    invisible to anyone not specifically watching scheduler-internal logs.
    Every job added to `scheduler` gets this guarantee automatically —
    nobody adding a new job later has to remember to hand-wrap it
    correctly for this baseline to hold.

    APScheduler invokes listeners synchronously even under
    AsyncIOScheduler, so the audit write (async) is scheduled onto the
    already-running loop via create_task rather than awaited directly
    here. Uses record_audit_best_effort, not record_audit: if the audit
    write itself fails too (e.g. the same DB outage that caused the
    original job failure), that failure is logged through this project's
    own structured logger instead of surfacing only via asyncio's default
    "Task exception was never retrieved" handler."""
    logger.error("scheduler.job_failed", job_id=event.job_id, error=str(event.exception))
    task = asyncio.create_task(
        record_audit_best_effort(
            "scheduled_job_failed", detail={"job_id": event.job_id, "error": str(event.exception)}
        )
    )
    _pending_job_error_audits.add(task)
    task.add_done_callback(_pending_job_error_audits.discard)


scheduler = AsyncIOScheduler()
scheduler.add_listener(_on_scheduled_job_error, EVENT_JOB_ERROR)
mcp_app = live_mcp.http_app(path="/", transport="streamable-http")

# Single source of truth for where the live session is mounted, derived from
# FASTMCP_BASE_URL's own path component (FastMCP's docs require base_url to
# include this path when mounting under a prefix, so it's already the
# authoritative value). The outer mount call and the discovery redirects
# below all read from this instead of repeating "/mcp" as a literal in four
# places, so they can't drift apart from each other or from FASTMCP_BASE_URL.
_MCP_MOUNT_PATH = urlparse(settings.fastmcp_base_url).path.rstrip("/") or "/mcp"
_MCP_MOUNT_SUFFIX = _MCP_MOUNT_PATH.lstrip("/")


async def _run_audit_log_purge() -> None:
    """SC-6 requires a 60-day retention minimum, not a maximum — this is what
    actually prunes rows once they're well past AUDIT_RETENTION_DAYS, rather
    than leaving the minimum satisfied only by nothing ever deleting early.
    Errors are caught and recorded the same way run_staging_cycle records
    per-tenant failures, rather than left to APScheduler's own internal
    logger — otherwise a failure here would be invisible to anyone not
    specifically watching scheduler-internal logs, for up to a full 24-hour
    cycle before the next attempt. The fallback record_audit call is itself
    guarded: it hits the same Postgres pool the purge itself just failed
    against, so if the real cause is a DB outage, that call would raise too
    — the plain logger.error above is what still gets through in that case,
    since it doesn't depend on Postgres at all. The fallback-audit guard
    itself is shared (auth.record_audit_best_effort) with
    sync/airtable_staging.py's own near-identical failure paths."""
    try:
        deleted = await purge_expired_audit_log()
        logger.info("audit_log_purge.completed", rows_deleted=deleted)
    except Exception as exc:
        logger.error("audit_log_purge.failed", error=str(exc))
        await record_audit_best_effort("audit_log_purge_failed", detail={"error": str(exc)})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_schema()

    # Run once now, not just on the 24h interval below: APScheduler's
    # IntervalTrigger schedules its first fire one full interval from now,
    # not immediately (confirmed directly against this project's installed
    # apscheduler version) — so without this, a service that gets restarted
    # more often than every 24 hours (plausible during active development,
    # or frequent redeploys) could go through its entire lifetime without
    # the purge ever actually running once.
    await _run_audit_log_purge()

    scheduler.add_job(
        run_staging_cycle,
        "interval",
        minutes=settings.sync_interval_minutes,
        id="staging_cycle",
    )
    scheduler.add_job(
        _run_audit_log_purge,
        "interval",
        hours=24,
        id="audit_log_purge",
    )
    scheduler.start()

    async with mcp_app.lifespan(_app):
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            await close_pool()


class _McpMountSlashCompatibility:
    """Two related fixes for how FastMCP's app behaves once mounted at an
    outer /mcp prefix, both confirmed live 2026-09-09 against a real MCP
    Inspector "Add connector" attempt — neither fixable by adding more
    routes, since both are baked in by FastMCP/Starlette before any route
    of ours ever runs:

    1. Request-path normalization (on the way in). A bare `POST /mcp` (no
    trailing slash — exactly the URL a client configures, since
    FASTMCP_BASE_URL/_MCP_MOUNT_PATH never have one) strips down to an
    empty remaining path inside the mounted app, which only has a route
    registered at "/" — Starlette's own default redirect_slashes behavior
    turns that into a 307 to /mcp/ before the real request is ever
    answered. Confirmed live: a real Inspector session's connection
    attempt fails immediately after exactly this redirect, reporting the
    post-redirect URL as a "protected resource" mismatch against the one
    it was configured with — independent of any metadata document or
    header content, which is why fixing those alone (see
    protected_resource_metadata below) didn't help. Rewriting the request
    path here, before Starlette's own router ever sees it, means the
    mounted app answers /mcp directly — no redirect, so the client only
    ever sees the one URL it actually asked for.

    2. WWW-Authenticate header correction (on the way out). FastMCP's
    RequireAuthMiddleware issues this challenge on every unauthenticated
    /mcp request, with its resource_metadata URL baked in once at
    app-construction time — the same fastmcp==4.0.0b2 trailing-slash bug
    as protected_resource_metadata's own (AuthProvider._get_resource_url
    always appends "/" when FastMCP's own internal mount path is "/",
    which this outer-mount setup requires). Kept even with fix 1 above,
    since a client that reads this header directly (rather than relying
    on which URL its own request happened to land on) needs the correct
    value too.

    A raw ASGI middleware, not Starlette's BaseHTTPMiddleware, deliberately:
    /mcp's real (authenticated) responses use Streamable HTTP, a
    potentially long-lived streaming transport, and BaseHTTPMiddleware
    buffers an entire response body to let middleware inspect/rewrite it —
    which would break that streaming. This only ever touches the scope's
    path (inbound) and the headers list on the single http.response.start
    message (outbound), never any body message, so it's safe no matter how
    long a downstream response streams for."""

    def __init__(self, app):
        self.app = app
        # e.g. b'/mcp/"' -> b'/mcp"' — narrow and specific to this exact
        # header's own trailing-slash-before-closing-quote shape, not a
        # blind global slash strip.
        self._broken = f'/{_MCP_MOUNT_SUFFIX}/"'.encode()
        self._fixed = f'/{_MCP_MOUNT_SUFFIX}"'.encode()

    async def __call__(self, scope, receive, send):
        # Both fixes below only ever matter for /mcp traffic — this
        # middleware still has to be global (see the comment where it's
        # registered), but there's no reason every other route in the app
        # (/health, the OAuth callback pages, the Sybill webhook,
        # /debug/hubspot/*) should pay for rebuilding its own response
        # headers on every request just to check for a header only /mcp
        # ever sends. Skip straight through, unwrapped, for anything else.
        path = scope.get("path", "")
        is_mcp_path = path == _MCP_MOUNT_PATH or path.startswith(f"{_MCP_MOUNT_PATH}/")
        if scope["type"] != "http" or not is_mcp_path:
            await self.app(scope, receive, send)
            return

        if scope["path"] == _MCP_MOUNT_PATH:
            scope = {**scope, "path": f"{_MCP_MOUNT_PATH}/"}

        async def _send(message):
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        (key, value.replace(self._broken, self._fixed) if key == b"www-authenticate" else value)
                        for key, value in message.get("headers", [])
                    ],
                }
            await send(message)

        await self.app(scope, receive, _send)


app = FastAPI(title="HubSpot MCP Server", version="0.2.0", lifespan=lifespan)

# Must be global (add_middleware), not a wrapper around just mcp_app at the
# mount call below: Starlette's own Mount already strips the /mcp prefix
# from scope["path"] before invoking whatever's mounted there, so a
# wrapper placed at the mount call itself never sees the unstripped path
# this middleware needs to rewrite (confirmed the hard way — an earlier
# version of this fix wrapped mcp_app directly, at the mount call, and the
# 307 it was meant to eliminate kept happening regardless). Global
# middleware sits outside Starlette's router entirely, so it always sees
# the original, unmodified request path no matter how any route or mount
# further in ends up matching it.
app.add_middleware(_McpMountSlashCompatibility)

app.include_router(hubspot_oauth_router)
app.include_router(token_vault_router)
app.include_router(sybill_router)
app.include_router(debug_api_router)
app.mount(_MCP_MOUNT_PATH, mcp_app)


@app.get(f"/.well-known/oauth-protected-resource/{_MCP_MOUNT_SUFFIX}")
@app.get(f"/.well-known/oauth-protected-resource/{_MCP_MOUNT_SUFFIX}/")
async def protected_resource_metadata() -> dict:
    """The live session's 401 challenge (WWW-Authenticate on /mcp) advertises
    this exact path as its resource_metadata URL — served directly here
    rather than redirected to FastMCP's own equivalent document (as this
    route used to do), because that document's own `resource` field is
    wrong: confirmed directly against the installed fastmcp==4.0.0b2 source
    (fastmcp/server/auth/auth.py::AuthProvider._get_resource_url), FastMCP
    mounts its own app at path="/" (main.py's outer /mcp mount already
    accounts for the prefix, so FastMCP's own internal root has to be "/"),
    and _get_resource_url's `path.lstrip("/")` on a bare "/" always yields
    "", after which it still appends a "/" — producing a spurious trailing
    slash no matter what base_url is. Confirmed live 2026-09-09: MCP
    Inspector rejects the mismatch outright ("Protected resource .../mcp/
    does not match expected .../mcp"), so this isn't cosmetic.

    Hand-built here instead of calling into FastMCP/the MCP SDK's own
    route-construction internals (mcp.server.auth.routes.
    create_protected_resource_routes) deliberately — the RFC 9728 shape
    needed is small and stable, and this avoids depending on FastMCP
    internals not meant to be called from outside the library, which could
    silently break on a future FastMCP upgrade. `scopes_supported` reads
    live off the real GoogleProvider instance rather than being duplicated
    here, so it can't drift out of sync with what _build_auth() actually
    configures."""
    return {
        "resource": settings.fastmcp_base_url,
        "authorization_servers": [settings.fastmcp_base_url],
        "scopes_supported": live_mcp.auth.required_scopes,
        "bearer_methods_supported": ["header"],
    }


@app.get(f"/.well-known/oauth-authorization-server/{_MCP_MOUNT_SUFFIX}")
async def authorization_server_metadata_redirect() -> RedirectResponse:
    """RFC 8414's standard discovery convention for an issuer with a path
    component (our issuer is http://localhost:8888/mcp) is to insert the path
    after the well-known segment: /.well-known/oauth-authorization-server/mcp.
    Real clients (confirmed against a live MCP Inspector session) request
    exactly that path. The metadata actually lives at
    /mcp/.well-known/oauth-authorization-server instead (outer mount prefix
    applied to FastMCP's own plain-registered route) — that combination isn't
    a standard discovery pattern, just an accident of how the mount and
    FastMCP's routing happen to line up, so no real client requests it
    directly. Redirect the standard path to the one that actually works."""
    return RedirectResponse(f"{_MCP_MOUNT_PATH}/.well-known/oauth-authorization-server")


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Reflects real service state: Postgres connectivity and scheduler status."""
    try:
        pool = await get_pool()
        await pool.fetchval("SELECT 1")
        db_ok = True
    except Exception as exc:
        logger.error("health_check.db_failed", error=str(exc))
        db_ok = False

    status = "healthy" if db_ok and scheduler.running else "degraded"
    return {
        "status": status,
        "postgres": "connected" if db_ok else "unreachable",
        "scheduler": "running" if scheduler.running else "stopped",
    }


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "service": "HubSpot MCP Server",
        "status": "running",
        "active_paths": [
            "hubspot-oauth",
            "token-vault",
            "airtable-staging",
            "sybill-ingestion",
            "live-mcp-session",
            "debug-hubspot-api",
        ],
    }
