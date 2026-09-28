# Predictive Maintenance Platform

## Local configuration

Create the local environment file before starting the stack:

```bash
cp .env.example .env
```

The example contains development-only credentials and service-discovery defaults.
Use independent secrets and production broker, database, email, and origin settings
for any deployed environment. Local `.env` files are intentionally not tracked.

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

The frontend build type-checks application, Node tooling, unit tests, and Playwright
tests before producing the Vite bundle. Run `npm run test:e2e` against a running
Compose stack; CI's deployment smoke workflow performs that full-system check.

## Docker Compose Modes

### Local development (default)

Use the base compose file for stable local networking and host port access:

```bash
docker compose up -d --build
```

This mode runs a single EMQX node (`emqx-main`).
It uses the local mock `source-broker` for deterministic development.

By default, anomaly detection containers are not started.
`mqtt-radar` is profile-gated and only starts when explicitly requested
or when created by the monitoring service workflow.

To run the standalone RADAR service manually:

```bash
docker compose --profile standalone-radar up -d mqtt-radar
```

Standalone RADAR also requires concrete topics for one charger. Configure
`RADAR_SUBSCRIPTION_TOPICS` as a comma-separated sensor list; wildcard topics are
rejected because they cannot define a stable multivariate feature schema.

### Monitoring architecture

The monitoring UI presents two lanes:

- **Static relationships** is the executable lane. It is intended for an aligned
  sensor set such as L1/L2/L3 whose dependency structure is expected to remain
  stable.
- **Temporally dependent streams** is a greyed-out, coming-soon preview. It has no
  model catalog, preprocessing pipeline, API contract, or runtime implementation.

A static service consumes consecutive, non-overlapping phases: baseline training,
calibration, and online inference. Inference produces one conformal p-value and
feeds the same ordered stream to every configured martingale tracker. Trackers may
use `power`, `simple_mixture`, or `simple_jumper` betting and may alarm on the
all-history martingale, harmonic restarted martingale, CUSUM, or
Shiryaev-Roberts statistic. An anomaly is emitted when any tracker records a new
threshold crossing. The backward-compatible default is power betting with
epsilon `0.5`, the restarted statistic, and threshold `100`.
The collapsed advanced-settings editor provides contextual info controls for
detector, tracker, threshold, and alignment fields; the same explanations open
on pointer hover and keyboard focus.

Ville thresholds on the all-history and harmonic restarted statistics retain
their anytime-valid interpretation. CUSUM and Shiryaev-Roberts thresholds are
change-detection parameters and must be calibrated for the intended null stream;
`1 / threshold` is not presented as their false-alarm probability.

Every ready-phase inference is persisted in `monitoring_evidence`, including the
p-value, sensor set, aggregate alarm flag, and bounded `tracker_results` evidence
for every configured martingale. Finite and infinite states are represented
explicitly. The legacy primary-tracker columns remain populated for compatibility.
The gateway exposes this evidence for telemetry charts, where each selected alarm
statistic is drawn on a logarithmic secondary axis with its threshold overlay.
Telemetry and evidence use the same normalized payload event timestamp. Their
stacked panes share horizontal bounds, zoom state, and crosshair, so observations
from one inference remain vertically aligned in time; receive time is used only
when a publisher omits its event timestamp.

An MQTT sensor stream may belong to only one active monitoring service. TACTIC
serializes claims in PostgreSQL and rejects overlapping MQTT filters, including `+`
and `#` wildcard overlap. Topic levels are literal: for example, charger IDs
`charger-1` and `charger-10` do not overlap.

### RADAR runtime image (local only)

TACTIC starts one RADAR workload for each monitoring service. Build its local
runtime image before creating a monitoring service for the first time:

```bash
docker compose build mqtt-radar
```

This builds `off-key-mqtt-radar:latest` without starting the profile-gated
standalone RADAR container. Rebuild it after RADAR dependencies or source code
change.

### MQTT simulator profile (local only)

`mqtt-simulator` is profile-gated (`mqtt-sim`) and is intended for local synthetic
telemetry generation only.

If your base stack is already running, start/recreate only the simulator with:

```bash
docker compose --profile mqtt-sim up -d --build --force-recreate mqtt-simulator
```

If you want to start everything including simulator in one command:

```bash
docker compose --profile mqtt-sim up -d --build
```

### AmbiBox catalog and collection

Open **Data sources** as a verified administrator to build or import the catalog,
select chargers and sensors, and apply original-rate or sampled collection. New
chargers start paused. The application manages per-broker EMQX sources and GOST
routes through private management APIs; topics are no longer configured in proxy
environment variables or a separate EMQX setup script.

The production deployment reuses the existing vendor tailnet identity and MQTT
credentials. For local Compose, import `dev/ambibox/local-catalog.json` and start
the `mqtt-sim` profile. See [AmbiBox collection](docs/operations/ambibox-collection.md)
for configuration semantics, limits, tests and the one-time clean cutover.

### EMQX two-node cluster mode

Enable cluster mode explicitly with the override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml up -d --build
```

This adds `emqx-worker` and updates EMQX seeds for a two-node cluster.

### Swarm deployment

Set production credentials and pinned image references in `.env`, then render
the Compose model before handing it to Swarm:

```bash
docker compose \
  --env-file .env \
  -f docker-compose.swarm.yml \
  config \
  | docker stack deploy --with-registry-auth -c - off-key
```

The render step is required because `docker stack deploy` does not load Compose
environment files for variable interpolation.

The existing per-service image variables can use either the convenience
`latest` tag or the already-published `sha-<commit>` tag. Pinning those same
variables to the SHA tag avoids an unchanged `latest` service specification and
does not change the deployment command. Verify what Swarm actually resolved:

```bash
docker stack services off-key --format '{{.Name}} {{.Image}}'
docker service inspect off-key_frontend \
  --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}'
docker service inspect off-key_mqtt-proxy \
  --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}'
```

On a node running a task, the OCI revision label proves which commit is inside
the container:

```bash
container_id=$(docker ps -q \
  --filter label=com.docker.swarm.service.name=off-key_frontend)
docker inspect "$container_id" \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}} {{.Image}}'
```

### Switching modes

When switching between local, ingress, and cluster modes, recreate resources to avoid stale
network/container DNS and namespace state:

```bash
docker compose down -v
docker network rm off-key_app-network off-key_emqx-network || true
```
