# Developer setup

This page documents the supported contributor setup and advanced debug workflows.

## When to use this page

Use this page when setting up a contributor environment, choosing a run mode, or running the local quality gates.

## Audience

- Contributors working on `backend/` or `frontend/`.
- Maintainers validating local developer environments before CI.

## Prerequisites

| Tool | Supported version or role |
| --- | --- |
| Python | 3.12 |
| [uv](https://docs.astral.sh/uv/) | Backend dependency and command runner |
| Node.js | 24 |
| npm | Frontend dependencies and scripts |
| Docker with Compose | Containerized stack |

## Install dependencies

From the repository root:

```bash
uv sync --project backend --all-packages --all-groups --frozen
npm --prefix frontend ci
```

Use `uv sync` without `--frozen` only when intentionally updating the backend lock state.

## Run modes — choose one intentionally

### Mode 1: Full stack in containers

```bash
cp .env.example .env
docker compose up -d --build
```

Use this mode for parity with documented local operations.

### Mode 2: Frontend on the host, backend in containers

1. Start the backend stack with Docker Compose.
2. Set the host-side frontend API URL to `http://localhost:8000`.
3. Start Vite:

```bash
npm --prefix frontend run dev
```

### Mode 3: Backend quality loop

```bash
uv run --project backend ruff check .
uv run --project backend python -m pytest -q
```

## Host versus container expectations

| Concern | Host runtime | Container runtime |
| --- | --- | --- |
| Gateway URL for frontend | `http://localhost:8000` | `http://api-gateway:8000` |
| Database host | Host-mapped address | Compose service name such as `timescaledb` |
| Log access | Process standard output | `docker compose logs -f <service>` |
| Networking | Published ports | Compose service DNS |

If requests fail after switching modes, check `VITE_API_URL` and the configured CORS origins first.

## Debug patterns

Follow the main backend services:

```bash
docker compose logs -f api-gateway tactic-middleware db-sync mqtt-proxy
```

Run a focused backend test from the root:

```bash
uv run --project backend python -m pytest path/to/test_file.py -q
```

For an IDE debugger, keep its environment aligned with `.env`, and use Compose service names only from code that runs inside the Compose networks.

## Pre-commit and local quality gate

```bash
uv run --project backend pre-commit install
uv run --project backend pre-commit run --all-files
uv run --project backend ruff check .
uv run --project backend python -m pytest -q
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

## Failure-oriented setup triage

| Symptom | Likely cause | First action |
| --- | --- | --- |
| Frontend cannot call the API in host mode | `VITE_API_URL` still uses container DNS | Set it to `http://localhost:8000` |
| Gateway restarts during boot | Database schema is not ready | Wait, then inspect `db-sync` and gateway logs |
| Monitoring endpoints return upstream errors | TACTIC is not ready or cannot reach the Docker API proxy | Check <http://localhost:8001/ready> and TACTIC logs |
| Pre-commit fails unexpectedly | Dependencies differ from the lockfiles | Re-run the frozen dependency installs |

## Related pages

- [Getting started](../getting-started.md)
- [Architecture](architecture.md)
- [Environment variables](../reference/environment-variables.md)
- [Testing and debugging](testing-debugging.md)
- [Contributing and CI](contributing-ci.md)
