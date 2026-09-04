# Machine Setup

This covers getting a machine ready to work on this repo at all: Docker, Python, and verifying the stack comes up. For the project's own configuration (`.env` values, HubSpot and Google Workspace account setup), see `README.md`.

## Docker

Docker Desktop is the recommended way to run and develop this project, since it matches the container's Python version exactly and avoids host-machine version drift.

1. Install Docker Desktop for your OS from docker.com.
2. Verify it's installed:
   ```bash
   docker --version
   ```
3. Verify the daemon is actually running (Docker Desktop must be open, not just installed):
   ```bash
   docker info
   ```
   If this hangs or errors, open Docker Desktop and wait for it to finish starting before continuing.

## Python (only needed for local development outside Docker)

The container image (`gateway/Dockerfile`) builds on `python:3.11-slim`. If your system Python is a different version, most commonly newer, code can behave differently locally than it will in the container, and that mismatch is easy to miss until the container build.

Two ways to handle this:

- **Recommended**: develop inside Docker (`docker compose up --build`) and skip managing a local Python version entirely.
- **Alternative**: install `pyenv`, pin a local `3.11.x`, and build your virtual environment against that specific version, so local and container match.

If you do want a local virtual environment for faster iteration:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
cd gateway && pip install -r requirements.txt
```

## Node.js (only needed for MCP Inspector)

Dev-only tooling, not needed to run the service itself — `package.json` at the
repo root exists solely to install `@modelcontextprotocol/inspector` for
poking at the live session's `/mcp` mount directly.

1. Install Node >=22.19 (an older Node still runs it, just with an
   `EBADENGINE` warning).
2. From the repo root:
   ```bash
   npm install
   ```
3. With the stack already running (`docker compose up`), launch it with no
   flags and add the server through the UI itself:
   ```bash
   npm run inspector
   ```
   Passing `--transport`/`--server-url` on the command line puts Inspector in
   a read-only "ad-hoc server" mode with no way to trigger the OAuth login —
   see `npm run inspector:cli` in `package.json` for the one case that's
   fine (headless `tools/list`, no login needed).

## HubSpot CLI project (`hubspot-app/`) — not part of `git clone`

`hubspot-app/` (the `hs project create` scaffold, including `app-hsmeta.json`,
the scope manifest) and `hubspot.config.yml` (the CLI's own per-device
personal access key) are both gitignored deliberately — the former isn't
source code this service runs, the latter is a per-device credential. Neither
comes down with a fresh `git clone`.

This is fine for the normal case: this project has exactly **one** shared
HubSpot Public App, registered once. A new machine just needs that existing
app's `HUBSPOT_APP_CLIENT_ID`/`HUBSPOT_APP_CLIENT_SECRET` (get them from a
teammate or your secrets manager, put them in `.env`) — there's no need to
touch the HubSpot CLI at all unless you're actually editing the app's scopes
or other manifest settings.

If you do need to edit the manifest (e.g. adding a scope), you need a local
checkout of the CLI project:

1. Install the CLI: `npm install -g @hubspot/cli`
2. Authenticate: `hs init` (or `hs auth`, if you already have a
   `hubspot.config.yml` from a previous `hs init`) — this is what creates the
   per-device `hubspot.config.yml`, using your own HubSpot account access.
3. Fetch the existing project rather than creating a new one — `hs project
   create` scaffolds a **new**, separate app; only use it for the project's
   original one-time bootstrap. Ask a teammate which command their HubSpot
   CLI version uses to clone an existing Developer Project's source (the
   exact subcommand has moved between CLI versions), or, in a pinch,
   hand-recreate `hubspot-app/src/app/app-hsmeta.json` from `.env.example`'s
   `HUBSPOT_SCOPES`/`HUBSPOT_OPTIONAL_SCOPES` comments, which document the
   exact confirmed-working scope list.
4. After editing, `hs project upload` to deploy the change — HubSpot
   validates installs against the app's own registered manifest, not what
   `.env`'s `HUBSPOT_SCOPES`/`HUBSPOT_OPTIONAL_SCOPES` says, so the two must
   always be edited together (see `context/ONBOARDING_RUNBOOK.md`).

## Verifying the stack

Bring up the full stack and confirm the service responds:

```bash
docker compose up -d --build
curl http://localhost:8888/health
```

`mcp-postgres` should show as healthy (`docker compose ps`), and `/health` should return `{"status":"healthy","postgres":"connected","scheduler":"running"}`. For a fuller check — the full pytest suite plus a live smoke test against every route — run `python3 scripts/test_all.py` from the repo root instead; it's also what CI runs on every push/PR to `dev`/`main` (`.github/workflows/ci.yml`).
