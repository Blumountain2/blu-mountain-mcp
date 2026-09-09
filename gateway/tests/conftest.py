"""Shared test fixtures. Sets safe dummy env vars before any application
module is imported, so tests never depend on real credentials, then
provides a real Postgres connection against the docker-compose service for
tests that need actual encryption/advisory-lock/rate-limit behavior."""

import base64
import os

# Unconditionally override with test doubles, never conditional on the var
# being unset or empty: docker-compose passes the real .env's values (empty
# or not) straight into this container's environment, so a `setdefault`-style
# check would let real production secrets leak into test runs (and, worse,
# into test failure output) whenever the real .env happens to have them set.
#
# DATABASE_URL deliberately points at a "mcp_test" database, NEVER at the
# real dev database ("mcp") that docker-compose up's own containers use:
# the _pool fixture below TRUNCATEs every table it touches after each test,
# and this database lives on the same Postgres server/volume as the real
# one. Pointing tests at "mcp" directly already destroyed a real, verified
# HubSpot tenant install twice in one session before this was added — the
# _schema fixture below creates "mcp_test" on first run if it doesn't exist
# yet, so this isolation happens automatically, not as a manual setup step.
_BASE_DATABASE_URL = os.environ.get("DATABASE_URL") or "postgresql://mcp:change-me@postgres:5432/mcp"
_TEST_DATABASE_URL = _BASE_DATABASE_URL.rsplit("/", 1)[0] + "/mcp_test"

_TEST_ENV = {
    "APP_ENCRYPTION_KEY": base64.urlsafe_b64encode(b"0" * 32).decode(),
    "HUBSPOT_APP_CLIENT_ID": "test-app-client-id",
    "HUBSPOT_APP_CLIENT_SECRET": "test-app-client-secret",
    "HUBSPOT_REDIRECT_URI": "http://localhost:8888/callback",
    "HUBSPOT_SCOPES": "crm.objects.contacts.read crm.objects.companies.read crm.objects.deals.read tickets",
    "HUBSPOT_OPTIONAL_SCOPES": "",
    "FASTMCP_GOOGLE_CLIENT_ID": "test-google-client-id",
    "FASTMCP_GOOGLE_CLIENT_SECRET": "test-google-client-secret",
    "FASTMCP_BASE_URL": "http://localhost:8888",
    "FASTMCP_OAUTH_REDIRECT_URI": "http://localhost:8888/mcp/auth/callback",
    "FASTMCP_ALLOWED_GOOGLE_DOMAINS": "blumountain.me",
    "AIRTABLE_API_KEY": "test-airtable-key",
    "AIRTABLE_BASE_ID": "appTEST00000000000",
    "SYBILL_WEBHOOK": "whsec_dGVzdC1zZWNyZXQta2V5LWZvci10ZXN0cw==",
    "DEBUG_API_KEY": "test-debug-api-key",
    "DATABASE_URL": _TEST_DATABASE_URL,
}
for _key, _value in _TEST_ENV.items():
    os.environ[_key] = _value

import asyncpg
import pytest_asyncio

import db
from config import settings

_TABLES = [
    "tokens",
    "tenants",
    "oauth_states",
    "rate_limit_buckets",
    "audit_log",
    "staff_tenant_restrictions",
    "live_session_selection",
    "hubspot_object_index",
    "analysis_content",
]


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _schema():
    # Maintenance connection to the always-present "postgres" database,
    # used only to create "mcp_test" if it doesn't exist yet — CREATE
    # DATABASE can't run against the database it's creating, or inside a
    # transaction, which asyncpg's plain (non-`.transaction()`) execute
    # avoids by default.
    admin_url = _TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    admin_conn = await asyncpg.connect(admin_url)
    try:
        exists = await admin_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'mcp_test'"
        )
        if not exists:
            await admin_conn.execute("CREATE DATABASE mcp_test")
    finally:
        await admin_conn.close()

    # A standalone connection for one-time schema setup, deliberately not
    # going through db.get_pool(): pytest-asyncio gives every test function
    # its own event loop by default, but asyncpg pools are bound to the loop
    # that created them, so the pool itself must be (re)created per test,
    # not shared at session scope. See _pool below.
    conn = await asyncpg.connect(settings.database_url)
    try:
        ddl = db._SCHEMA_PATH.read_text()
        await conn.execute(ddl)
    finally:
        await conn.close()


@pytest_asyncio.fixture(autouse=True)
async def _pool():
    """Fresh pool per test, bound to that test's event loop, cleaned up after."""
    db._pool = None
    pool = await db.get_pool()
    yield pool
    async with pool.acquire() as conn:
        for table in _TABLES:
            await conn.execute(f"TRUNCATE TABLE {table} CASCADE")
    await db.close_pool()
