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


app = FastAPI(title="HubSpot MCP Server", version="0.2.0", lifespan=lifespan)

app.include_router(hubspot_oauth_router)
app.include_router(token_vault_router)
app.include_router(sybill_router)
app.include_router(debug_api_router)
app.mount(_MCP_MOUNT_PATH, mcp_app)


@app.get(f"/.well-known/oauth-protected-resource/{_MCP_MOUNT_SUFFIX}")
@app.get(f"/.well-known/oauth-protected-resource/{_MCP_MOUNT_SUFFIX}/")
async def protected_resource_metadata_redirect() -> RedirectResponse:
    """The live session's 401 challenge (WWW-Authenticate on /mcp) advertises
    this exact path as its resource_metadata URL. FastMCP builds that URL from
    its own base_url; it has no way to know main.py additionally mounts the
    whole app under /mcp on top of that, so the advertised URL is missing that
    outer prefix and 404s on its own. The real, correctly-populated document
    only exists at /mcp/.well-known/oauth-protected-resource/mcp/ (outer mount
    prefix + FastMCP's own RFC 9728 path suffix, confirmed working). Redirect
    clients there rather than editing FastMCP's own header-construction logic,
    which we don't control from here."""
    return RedirectResponse(
        f"{_MCP_MOUNT_PATH}/.well-known/oauth-protected-resource/{_MCP_MOUNT_SUFFIX}/"
    )


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
