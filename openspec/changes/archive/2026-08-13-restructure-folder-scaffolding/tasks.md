## 1. auth/ subpackage

- [x] 1.1 Create `gateway/auth/` and add a minimal `gateway/auth/__init__.py` (empty initially)
- [x] 1.2 Move `gateway/crypto.py` → `gateway/auth/crypto.py`; update any intra-package imports
- [x] 1.3 Move `gateway/security.py` → `gateway/auth/security.py`; update imports (`from db import` → `from db import`)
- [x] 1.4 Move `gateway/hubspot_oauth.py` → `gateway/auth/hubspot_oauth.py`; update imports
- [x] 1.5 Move `gateway/token_vault.py` → `gateway/auth/token_vault.py`; update imports
- [x] 1.6 Update `gateway/auth/__init__.py` to re-export the public surface needed by `main.py` (router, key classes)
- [x] 1.7 Update `gateway/main.py` to import from `auth` instead of individual module files
- [x] 1.8 Create `gateway/tests/auth/` with an empty `__init__.py`; move `test_crypto.py`, `test_security.py`, `test_hubspot_oauth.py`, `test_token_vault.py` into it and update their imports (also moved `test_hubspot_webhook.py`, which tests `token_vault`'s uninstall route and signature check — auth-subsystem, not cross-subsystem)
- [x] 1.9 Run `pytest gateway/tests/` — all tests must pass; run `curl localhost:8888/health` against `docker compose up` to confirm no runtime errors

## 2. sync/ subpackage

- [x] 2.1 Create `gateway/sync/` and add a minimal `gateway/sync/__init__.py`
- [x] 2.2 Move `gateway/hubspot_client.py` → `gateway/sync/hubspot_client.py`; update imports
- [x] 2.3 Move `gateway/airtable_staging.py` → `gateway/sync/airtable_staging.py`; update imports
- [x] 2.4 Update `gateway/sync/__init__.py` to re-export the scheduler entry-point and any public classes
- [x] 2.5 Update `gateway/main.py` to import from `sync`
- [x] 2.6 Create `gateway/tests/sync/` with an empty `__init__.py`; move `test_hubspot_client.py` and `test_airtable_staging.py` into it and update their imports
- [x] 2.7 Run `pytest gateway/tests/` — all tests must pass; confirm health endpoint

## 3. webhooks/ subpackage

- [x] 3.1 Create `gateway/webhooks/` and add a minimal `gateway/webhooks/__init__.py`
- [x] 3.2 Move `gateway/sybill_webhook.py` → `gateway/webhooks/sybill.py` (rename to drop the redundant `_webhook` suffix); update imports
- [x] 3.3 Update `gateway/webhooks/__init__.py` to re-export the Sybill router
- [x] 3.4 Update `gateway/main.py` to import from `webhooks`
- [x] 3.5 Create `gateway/tests/webhooks/` with an empty `__init__.py`; move `test_sybill_webhook.py` into it (rename to `test_sybill.py`) and update its imports
- [x] 3.6 Run `pytest gateway/tests/` — all tests must pass; confirm health endpoint

## 4. session/ subpackage

**Renamed from the originally planned `mcp/` to `session/`** (discovered during implementation, not a pre-existing task revision): this project depends on `fastmcp`, which itself depends on the official `mcp` PyPI SDK, imported internally as `import mcp.types` etc. Because `/app` (the gateway root) is prepended to `sys.path` ahead of site-packages, a local subpackage literally named `mcp` shadows that real dependency — confirmed empirically, it breaks with `ModuleNotFoundError: No module named 'mcp.types'` / `ImportError: FastMCP server support is not installed.` at container startup. `session/` was chosen with the user after flagging this; see design.md's Decisions section for the record.

- [x] 4.1 Create `gateway/session/` and add a minimal `gateway/session/__init__.py`
- [x] 4.2 Move `gateway/cowork_session.py` → `gateway/session/cowork_session.py`; update imports
- [x] 4.3 Move `gateway/staff_direct_auth.py` → `gateway/session/staff_auth.py` (rename for consistency); update imports
- [x] 4.4 Update `gateway/session/__init__.py` to re-export the MCP app and staff auth router/dependency
- [x] 4.5 Update `gateway/main.py` to import from `session`
- [x] 4.6 Create `gateway/tests/session/` with an empty `__init__.py`; move relevant staff-auth and session tests into it and update imports (none existed to move — only the cross-subsystem `test_tenant_isolation.py`, which stays at `tests/` root, touches `cowork_session`)
- [x] 4.7 Run `pytest gateway/tests/` — all tests must pass; run `docker compose up` and confirm `/health` and `/staff/me` both respond correctly

## 5. Verification

- [x] 5.1 Confirm no `.py` files remain at `gateway/` root other than `main.py`, `config.py`, `db.py`
- [x] 5.2 Confirm `gateway/tests/` root contains only `conftest.py` and any cross-subsystem security test files; all subsystem tests are inside subdirectories (also added an empty `gateway/tests/__init__.py`, required to prevent `tests/<subpackage>/` from shadowing the same-named production packages on `sys.path` — see design.md)
- [x] 5.3 Run full test suite (`pytest gateway/tests/ -v`) — zero failures, zero import errors (58 passed)
- [x] 5.4 Run `docker compose up -d` and confirm `GET /health` returns HTTP 200 and `GET /staff/me` returns HTTP 401 for a missing token (same behavior as before the restructure)
- [x] 5.5 Grep for any remaining imports of old flat paths (e.g., `from crypto import`, `from hubspot_oauth import`, `from sybill_webhook import`) — expect zero results (zero found)
