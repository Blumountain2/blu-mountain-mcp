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

## Verifying the stack

Bring up the full stack and confirm the service responds:

```bash
docker compose up -d --build
curl http://localhost:8888/health
```

`mcp-postgres` should show as healthy (`docker compose ps`), and `/health` should return `{"status":"healthy","postgres":"connected","scheduler":"running"}`. For a fuller check — the full pytest suite plus a live smoke test against every route — run `python3 scripts/test_all.py` from the repo root instead; it's also what CI runs on every push/PR to `dev`/`main` (`.github/workflows/ci.yml`).
