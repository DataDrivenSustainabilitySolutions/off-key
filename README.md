<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/logo-white.svg">
  <img src="assets/brand/logo-black.svg" width="64" height="64" alt="Aberration mark">
</picture>

# Aberration

Predictive maintenance for connected systems: collect MQTT telemetry, run
anomaly-monitoring pipelines on it and review the evidence. Vector sources and
export instructions are in [Brand assets](assets/brand/README.md).

## Local configuration

Create the local environment file before starting the stack:

```bash
cp .env.example .env
docker swarm init --advertise-addr 127.0.0.1  # once per Docker engine; RADAR runs as Swarm services
docker compose up -d --build
```

The example contains development-only credentials and service-discovery defaults.
Use independent secrets and production broker, database, email, and origin settings
for any deployed environment. Local `.env` files are intentionally not tracked.
See [Deployment modes](docs/operations/deployment-modes.md) for the simulator
profile, the EMQX cluster override and production.

## Development validation

The container runtime uses Python 3.14; CI tests the backend on Python 3.12 and
3.14. Use `uv` for the backend workspace and Node.js 24 with `npm` for the frontend.

```bash
uv sync --project backend --all-packages --all-groups --frozen
uv run --project backend ruff check .
uv run --project backend python -m pytest -q

cd frontend
npm ci
npm run lint
npm test
npm run build
```

For branch coverage, add `--cov` to the backend pytest command (the root
`.coveragerc` measures every backend package; database, collection and Swarm lanes
skip unless their environment is set) and run `npm run test:coverage` in `frontend/`,
which writes an HTML report to `frontend/coverage/`.

The frontend build type-checks application, Node tooling, unit tests, and Playwright
tests before producing the Vite bundle. Run the browser journeys against a running
Compose stack, in two separate invocations because they need different TACTIC
settings: `npm run test:e2e` covers the default lanes and needs
`TACTIC_PIPELINE_AUTHORING_ENABLED=false`, and `npm run test:e2e:pipelines` covers the
visual-pipeline lane and needs it `true`. CI's deployment smoke workflow runs both.

## Documentation

The documentation site is built from [`docs/`](docs/index.md):

- [Getting started](docs/getting-started.md) and [local deployment](docs/development/local-deployment.md)
- [Monitoring](docs/user-guide/monitoring.md) and the [web app](docs/user-guide/web-app.md)
- [Architecture](docs/development/architecture.md) and [monitoring pipelines](docs/development/monitoring-pipelines.md)
- [Collection](docs/operations/system-collection.md), [production releases](docs/operations/production.md) and [recovery](docs/operations/recovery.md)
- [Contributing and CI](docs/development/contributing-ci.md)
