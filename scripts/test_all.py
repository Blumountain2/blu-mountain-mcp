#!/usr/bin/env python3
"""Single entry point proving the health of everything built so far, plus an
explicit, honest accounting of what's blocked or still open.

Usage: python scripts/test_all.py
(Run from anywhere; this script locates the repo root itself.)

Exit code 0 means everything this script CAN test is passing. It cannot
test what's blocked on real HubSpot/Google credentials, that's a real
limit, not something this script hides.

Python-only, standard library only (subprocess + urllib): start Postgres,
build the real image, run the automated test suite against it, then hit
the live container with real HTTP requests. This is also the entry point
.github/workflows/ci.yml runs on every push/PR to dev or main.
"""

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
overall_pass = True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Report our own server's redirect status code (e.g. 307 to HubSpot's
    authorize URL) instead of following it, matching curl's default
    behavior (which the bash version of this script relies on)."""

    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def section(title: str) -> None:
    print()
    print("=" * 67)
    print(title)
    print("=" * 67)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT_DIR, **kwargs)


def check_http(desc: str, url: str, expected_status: int, method: str = "GET",
                headers: dict | None = None, data: bytes | None = None) -> None:
    global overall_pass
    request = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        with _opener.open(request, timeout=5) as response:
            actual = response.status
    except urllib.error.HTTPError as exc:
        actual = exc.code
    except urllib.error.URLError as exc:
        print(f"  FAIL  {desc} (could not connect: {exc.reason})")
        overall_pass = False
        return

    if actual == expected_status:
        print(f"  OK    {desc} ({actual})")
    else:
        print(f"  FAIL  {desc} (expected {expected_status}, got {actual})")
        overall_pass = False


def main() -> int:
    global overall_pass

    section("1. Postgres")
    # --wait blocks until the service's own healthcheck (pg_isready, defined
    # in docker-compose.yml) reports healthy, instead of a one-shot check
    # immediately after `up -d` returns — that one-shot check races against
    # Postgres actually accepting connections, and loses often enough on a
    # colder/slower CI runner to fail this step even though Postgres comes
    # up fine moments later.
    up = run(["docker", "compose", "up", "-d", "--wait", "postgres"])
    if up.returncode != 0:
        print("Postgres did not become healthy in time.")
        overall_pass = False

    section("2. Building the gateway image (current code, no volume-mount shortcuts)")
    build = run(["docker", "compose", "build", "mcp-gateway"])
    if build.returncode != 0:
        print("Image build FAILED.")
        return 1

    section("3. Automated test suite (real Postgres, no live external credentials)")
    test_run = run([
        "docker", "compose", "run", "--rm", "--user", "0", "mcp-gateway", "sh", "-c",
        "pip install -q -r requirements-dev.txt && pytest -q",
    ])
    test_result = "PASSED" if test_run.returncode == 0 else "FAILED"
    if test_run.returncode != 0:
        overall_pass = False
    print(f"Test suite result: {test_result}")

    section("4. Live smoke test (starts the real container, sends real HTTP requests)")
    run(["docker", "compose", "up", "-d"])
    time.sleep(3)

    check_http("GET /health returns 200", "http://localhost:8888/health", 200)
    check_http("GET / returns 200", "http://localhost:8888/", 200)
    check_http("GET /install redirects to HubSpot", "http://localhost:8888/install", 307)
    check_http("GET /callback with missing params rejected", "http://localhost:8888/callback", 400)
    check_http(
        "POST /webhooks/sybill bad signature rejected",
        "http://localhost:8888/webhooks/sybill", 401, method="POST",
        headers={"svix-id": "x", "svix-timestamp": "1", "svix-signature": "bad"},
        data=b"{}",
    )
    check_http(
        "POST /webhooks/hubspot/uninstall unsigned rejected",
        "http://localhost:8888/webhooks/hubspot/uninstall", 400, method="POST",
        data=b"{}",
    )

    try:
        with urllib.request.urlopen("http://localhost:8888/health", timeout=5) as response:
            health_json = response.read().decode()
    except urllib.error.URLError as exc:
        health_json = f"<could not connect: {exc.reason}>"

    print(f"  /health payload: {health_json}")
    if '"postgres":"connected"' in health_json and '"scheduler":"running"' in health_json:
        print("  OK    /health reports real Postgres+scheduler state")
    else:
        print("  FAIL  /health did not report a fully healthy state")
        overall_pass = False

    section("5. Project health report")
    print("""\
Built and verified by this script:
  - token-vault        (Postgres schema, HKDF+AES-256, cache, refresh, advisory locks, uninstall webhook)
  - hubspot-oauth       (PKCE install/callback, RFC 6749 error handling)
  - mcp-auth            (second PKCE install/callback for the MCP Auth App, spec Section 4.1)
  - hubspot-data-pull   (per-tenant client, read-only enforcement, tenant isolation)
  - airtable-staging    (schema, normalization, scheduled job, client tagging)
  - sybill-ingestion    (Svix signature verification, transcript normalization)
  - live-mcp-session    (FastMCP OAuth Proxy, domain allowlist, tenant selection, audit)
  - security-hardening  (rate limiting, audit log)
  - All 10 Security Controls (SC-1 through SC-10):
      see context/Hubspot/SECURITY_CONTROLS_CHECKLIST.md

Confirmed against real HubSpot credentials manually (not by this script,
which only runs against test doubles/no external credentials):
  - HubSpot Public App + MCP Auth App (spec Section 4.1) — both installs
    completed against two test portals (hub_id=148997330, hub_id=149094230)
  - A full end-to-end pull confirmed real across every read path: the core
    CRM object set, generic per-object tools (with required default
    parameters), per-campaign metrics, and every reference object named in
    spec Section 4.4 (teams, segments, landing pages, blog posts, campaigns)
  - Account-tier-gated features (Campaigns) confirmed working on the
    Enterprise-tier test portal, and confirmed to degrade gracefully
    (no crash) on the portal without that tier

Blocked on manual action — this script CANNOT test this, no amount of
code changes here substitutes for it:
  - Registering the Google Cloud OAuth client for the live session\
""")

    print()
    if overall_pass:
        print("OVERALL: HEALTHY — everything testable right now is passing.")
        return 0
    else:
        print("OVERALL: FAILED — see the FAIL lines above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
