"""Per-tenant token vault: encrypted storage, cache, proactive refresh,
advisory-lock-serialized concurrency, and HubSpot uninstall handling.
"""

import hashlib
import hmac
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

import structlog
from fastapi import APIRouter, HTTPException, Request

from db import get_pool

from .crypto import decrypt, derive_tenant_key, encrypt
from .hubspot_oauth import refresh_token_pair
from .security import record_audit

logger = structlog.get_logger()

router = APIRouter()

_REFRESH_BUFFER = timedelta(minutes=5)
_REPLAY_WINDOW_SECONDS = 5 * 60


class AccessTokenCache(ABC):
    """Pluggable cache interface. Async because a real multi-instance-shared
    backing (PostgresAccessTokenCache below) can only ever be async — a
    synchronous interface here would have made a Postgres-backed
    implementation impossible to write correctly, which is exactly why
    only the in-process fallback existed for a while."""

    @abstractmethod
    async def get(self, hub_id: str) -> str | None: ...

    @abstractmethod
    async def set(self, hub_id: str, access_token: str, expires_at: datetime) -> None: ...

    @abstractmethod
    async def invalidate(self, hub_id: str) -> None: ...


class InMemoryAccessTokenCache(AccessTokenCache):
    """Per-spec (Section 3.1), kept available behind the same interface for
    local development; no longer TokenVault's default — see
    PostgresAccessTokenCache below."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, datetime]] = {}

    async def get(self, hub_id: str) -> str | None:
        entry = self._store.get(hub_id)
        if entry is None:
            return None
        access_token, expires_at = entry
        if datetime.now(timezone.utc) >= expires_at:
            del self._store[hub_id]
            return None
        return access_token

    async def set(self, hub_id: str, access_token: str, expires_at: datetime) -> None:
        # Refresh tokens are never placed in this cache (FR-5): only the
        # access token and its own expiry are stored here.
        self._store[hub_id] = (access_token, expires_at)

    async def invalidate(self, hub_id: str) -> None:
        self._store.pop(hub_id, None)


class PostgresAccessTokenCache(AccessTokenCache):
    """The spec's required multi-instance baseline (Section 3.1: "Because
    the deployment is multi-instance from launch, a Postgres-backed cache
    is the baseline"). TokenVault's default as of this fix — previously
    only InMemoryAccessTokenCache existed, which silently breaks cache
    consistency the moment a second mcp-gateway instance runs.

    Rather than a second table, this reads the same encrypted-token row
    every TokenVault instance already persists to table_name — every
    instance sees the same state for free, with no separate write path to
    keep in sync. set()/invalidate() are deliberately no-ops:
    get_access_token()'s own refresh path is what writes that row, and
    invalidate_in_transaction() is what deletes it; a second write path
    here would just be a second place for the two to drift apart. What
    this actually saves over always falling through to get_access_token()'s
    full path is the advisory-lock transaction on every call — this does a
    lock-free read instead, only falling through on an actual miss (no
    row, a decrypt failure, or past expiry)."""

    def __init__(self, table_name: str) -> None:
        self._table_name = table_name

    async def get(self, hub_id: str) -> str | None:
        pool = await get_pool()
        row = await pool.fetchrow(
            f"SELECT encrypted_access_token, expires_at FROM {self._table_name} WHERE hub_id = $1",
            hub_id,
        )
        # Must honor the same _REFRESH_BUFFER get_access_token()'s own
        # refresh check uses, not just hard expiry — unlike
        # InMemoryAccessTokenCache (only ever populated by a value that
        # already passed that check), this reads a row that could be
        # anyone's state, including one nobody has refreshed in a while.
        # Without this, a near-expiry row would be served straight from
        # here forever, since a hard-expiry-only check never sees it as a
        # miss until it's already too late to refresh proactively.
        if row is None or datetime.now(timezone.utc) >= row["expires_at"] - _REFRESH_BUFFER:
            return None
        try:
            return decrypt(row["encrypted_access_token"], derive_tenant_key(hub_id))
        except Exception:
            return None

    async def set(self, hub_id: str, access_token: str, expires_at: datetime) -> None:
        pass

    async def invalidate(self, hub_id: str) -> None:
        pass


# The per-table event names and uninstall-semantics are a deterministic
# function of which table a vault is backed by, not an independent choice a
# caller could get wrong — deriving them here means a vault for a given
# table always behaves the same way, everywhere it's constructed.
_TOKEN_TABLE_CONFIG = {
    "tokens": {
        "refresh_event": "token_refreshed",
        "invalidate_event": "token_invalidated",
        "mark_tenant_uninstalled_on_invalidate": True,
    },
    "mcp_tokens": {
        "refresh_event": "mcp_token_refreshed",
        "invalidate_event": "mcp_token_invalidated",
        "mark_tenant_uninstalled_on_invalidate": False,
    },
}

PUBLIC_APP_TOKEN_TABLE = "tokens"


async def acquire_tenant_lock(conn, hub_id: str, table_name: str = PUBLIC_APP_TOKEN_TABLE) -> None:
    """Acquires the same per-tenant, per-table advisory lock TokenVault
    itself uses below, scoped to conn's current transaction (released
    automatically at transaction end). Exposed so a cross-cutting mutation
    outside TokenVault (mcp_auth.py's install-order check, which reads
    tenants.install_status — a fact only vault.invalidate() mutates) can
    serialize against that vault's operations for the same hub_id instead
    of racing it. Table-scoped, not just hub_id-scoped, so vault and
    mcp_vault never needlessly block each other's refresh/invalidate for
    the same tenant — they're independent tables with no data dependency
    between them. Validated against the same _TOKEN_TABLE_CONFIG TokenVault
    itself validates against — a typo'd or unrecognized table_name here
    would otherwise silently lock a different key than TokenVault's own
    calls use for that table, defeating the serialization a caller (e.g.
    mcp_auth.py's install-order check) relies on this to provide."""
    if table_name not in _TOKEN_TABLE_CONFIG:
        raise ValueError(f"Unrecognized token table: {table_name}")
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1 || ':' || $2))", hub_id, table_name)


class TokenVault:
    """Parameterized by table_name/refresh_fn so a second instance (the MCP
    Auth App's mcp_tokens, see mcp_auth.py) can reuse this exact
    advisory-lock + cache + proactive-refresh logic without duplicating it —
    the two credentials have an identical lifecycle, just against different
    tables and different HubSpot token endpoints. table_name is restricted
    to _TOKEN_TABLE_CONFIG's keys since it's interpolated directly into SQL
    (no placeholder syntax exists for identifiers); this is safe only because
    it's fixed at construction time by our own code, never external input."""

    def __init__(
        self,
        cache: AccessTokenCache | None = None,
        table_name: str = "tokens",
        refresh_fn: Callable[[str], Awaitable[tuple[str, str, datetime]]] | None = None,
    ) -> None:
        if table_name not in _TOKEN_TABLE_CONFIG:
            raise ValueError(f"Unrecognized token table: {table_name}")
        config = _TOKEN_TABLE_CONFIG[table_name]
        self._cache = cache or PostgresAccessTokenCache(table_name)
        self._table_name = table_name
        # Bound once here, deliberately, not re-looked-up as a module global
        # inside get_access_token: this instance's refresh function is a
        # construction-time fact (mcp_vault always needs mcp_auth's, vault
        # always needs hubspot_oauth's), not something meant to vary call to
        # call. A test that wants a different refresh_fn must construct a
        # fresh TokenVault()/token_vault._mcp_vault() after monkeypatching —
        # every test in this codebase already does exactly that.
        self._refresh_fn = refresh_fn if refresh_fn is not None else refresh_token_pair
        self._refresh_event = config["refresh_event"]
        self._invalidate_event = config["invalidate_event"]
        self._mark_tenant_uninstalled_on_invalidate = config["mark_tenant_uninstalled_on_invalidate"]

    async def get_access_token(self, hub_id: str) -> str:
        """Returns a valid access token for this tenant, refreshing proactively
        (5-minute buffer) if needed. Serialized per tenant via advisory lock so
        concurrent instances never double-refresh the same tenant."""
        cached = await self._cache.get(hub_id)
        if cached is not None:
            return cached

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # pg_advisory_xact_lock auto-releases at transaction end, and
                # is scoped per hub_id AND per table, so tenants never block
                # each other, and vault/mcp_vault never block each other for
                # the same tenant — only concurrent operations against the
                # SAME table for the SAME tenant do.
                await acquire_tenant_lock(conn, hub_id, self._table_name)

                row = await conn.fetchrow(
                    f"SELECT encrypted_access_token, encrypted_refresh_token, expires_at "
                    f"FROM {self._table_name} WHERE hub_id = $1",
                    hub_id,
                )
                if row is None:
                    raise HTTPException(404, "Unknown tenant")

                key = derive_tenant_key(hub_id)
                expires_at: datetime = row["expires_at"]

                if datetime.now(timezone.utc) >= expires_at - _REFRESH_BUFFER:
                    refresh_token = decrypt(row["encrypted_refresh_token"], key)
                    access_token, new_refresh_token, new_expires_at = await self._refresh_fn(
                        refresh_token
                    )
                    await conn.execute(
                        f"""
                        UPDATE {self._table_name}
                        SET encrypted_access_token = $2,
                            encrypted_refresh_token = $3,
                            expires_at = $4,
                            last_refreshed_at = now()
                        WHERE hub_id = $1
                        """,
                        hub_id,
                        encrypt(access_token, key),
                        encrypt(new_refresh_token, key),
                        new_expires_at,
                    )
                    logger.info("token_vault.refreshed", hub_id=hub_id, table=self._table_name)
                    refreshed = True
                else:
                    access_token = decrypt(row["encrypted_access_token"], key)
                    new_expires_at = expires_at
                    refreshed = False

        await self._cache.set(hub_id, access_token, new_expires_at)
        if refreshed:
            await record_audit(self._refresh_event, hub_id=hub_id)
        return access_token

    @property
    def invalidate_event(self) -> str:
        return self._invalidate_event

    async def invalidate_in_transaction(self, conn, hub_id: str) -> None:
        """The DB half of invalidate(), against an already-open
        transaction/connection the caller owns. Exposed as its own method
        so hubspot_uninstall_webhook can invalidate both vault and
        mcp_vault's rows (and the shared tenants.install_status flip) in
        ONE transaction — a failure partway through rolls back everything
        rather than leaving one vault's row deleted and the other's
        orphaned. invalidate() below is just this wrapped in its own
        connection for the common single-vault case."""
        await self._cache.invalidate(hub_id)
        await acquire_tenant_lock(conn, hub_id, self._table_name)
        await conn.execute(f"DELETE FROM {self._table_name} WHERE hub_id = $1", hub_id)
        if self._mark_tenant_uninstalled_on_invalidate:
            await conn.execute(
                "UPDATE tenants SET install_status = 'uninstalled', updated_at = now() "
                "WHERE hub_id = $1",
                hub_id,
            )

    async def invalidate(self, hub_id: str) -> None:
        """Invalidates a tenant's stored token set (uninstall). Re-authorization
        via /install creates a fresh row (ON CONFLICT DO UPDATE in hubspot_oauth)."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await self.invalidate_in_transaction(conn, hub_id)
        await record_audit(self._invalidate_event, hub_id=hub_id)


vault = TokenVault()


def _mcp_vault() -> TokenVault:
    # Deferred import: mcp_auth imports from hubspot_oauth (not from this
    # module), so this doesn't create a cycle, but importing it lazily here
    # keeps that dependency direction obvious rather than hidden at the top
    # of the file alongside the Public App's own default.
    from .mcp_auth import refresh_token_pair as mcp_refresh_token_pair

    return TokenVault(table_name="mcp_tokens", refresh_fn=mcp_refresh_token_pair)


mcp_vault = _mcp_vault()


async def get_installed_hub_ids() -> list[str]:
    """Every tenant currently installed. Single source of truth for "which
    tenants are active" — shared by the scheduled sync (sync/airtable_staging.py)
    and the live session's default-open tenant access
    (session/live_session.py), so the two can never silently disagree on
    what counts as an active tenant."""
    pool = await get_pool()
    rows = await pool.fetch("SELECT hub_id FROM tenants WHERE install_status = 'installed'")
    return [row["hub_id"] for row in rows]


def verify_hubspot_webhook_signature(body: bytes, signature_header: str, client_secret: str) -> bool:
    """HMAC SHA-256 validation for HubSpot's app-lifecycle webhook (SC-5)."""
    expected = hmac.new(client_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


@router.post("/webhooks/hubspot/uninstall")
async def hubspot_uninstall_webhook(request: Request) -> dict:
    from config import settings

    body = await request.body()
    signature = request.headers.get("X-HubSpot-Signature-V3", "")
    timestamp_header = request.headers.get("X-HubSpot-Request-Timestamp", "0")

    try:
        request_time = int(timestamp_header) / 1000
    except ValueError:
        raise HTTPException(400, "Invalid timestamp header")

    if abs(time.time() - request_time) > _REPLAY_WINDOW_SECONDS:
        logger.warning("hubspot_webhook.stale_request")
        raise HTTPException(400, "Stale request")

    if not verify_hubspot_webhook_signature(body, signature, settings.hubspot_app_client_secret):
        logger.warning("hubspot_webhook.invalid_signature")
        raise HTTPException(401, "Invalid signature")

    payload = await request.json()
    hub_id = str(payload.get("portalId") or payload.get("hub_id") or "")
    if not hub_id:
        raise HTTPException(400, "Missing portal identifier")

    # The MCP Auth App is a separate credential for the same portal (see
    # mcp_auth.py) — HubSpot's uninstall webhook only ever names the Public
    # App, but both credentials become dead the moment a client uninstalls.
    # Both purges run in ONE transaction (not two independent invalidate()
    # calls) so a transient failure on the second can't orphan a live
    # mcp_tokens row for a tenant this system's own tenants table already
    # considers uninstalled.
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await vault.invalidate_in_transaction(conn, hub_id)
            await mcp_vault.invalidate_in_transaction(conn, hub_id)
    await record_audit(vault.invalidate_event, hub_id=hub_id)
    await record_audit(mcp_vault.invalidate_event, hub_id=hub_id)
    logger.info("hubspot_webhook.uninstalled", hub_id=hub_id)
    return {"status": "invalidated", "hub_id": hub_id}
