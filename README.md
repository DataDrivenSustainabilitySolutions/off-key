<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/logo-white.svg">
  <img src="assets/brand/logo-black.svg" width="64" height="64" alt="Aberration mark">
</picture>

# Aberration

Predictive maintenance for connected systems. Vector sources and export
instructions are in [Brand assets](assets/brand/README.md).

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

For branch coverage, add `--cov` to the backend pytest command (the root
`.coveragerc` measures every backend package; database, collection and Swarm lanes
skip unless their environment is set) and run `npm run test:coverage` in `frontend/`,
which writes an HTML report to `frontend/coverage/`.

The frontend build type-checks application, Node tooling, unit tests, and Playwright
tests before producing the Vite bundle. Run `npm run test:e2e` against a running
Compose stack; CI's deployment smoke workflow performs that full-system check.

## Docker Compose Modes

### Local development (default)

For an isolated deployment of a rework, including a compiled frontend, real
authentication, persistent database, email capture, and local MQTT services, use
the [local deployment workflow](docs/development/local-deployment.md). It builds
the current checkout and runs alongside other previews without sharing their
database or image tags.

Use the base compose file for stable local networking and host port access.
RADAR workloads run as Swarm services, so the engine must be a Swarm manager:

```bash
docker swarm init --advertise-addr 127.0.0.1  # once per Docker engine
docker compose up -d --build
```

This mode runs a single EMQX node (`emqx-main`).
It uses the local mock `source-broker` for deterministic development.

RADAR workloads are not part of the baseline stack. TACTIC creates one for
each monitoring service started from the UI.

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
explicitly. The existing primary-tracker columns remain populated for database consistency.
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

RADAR owns MQTT reconnection. A failed connection is fully retired before its
replacement starts, and shutdown joins the owned network thread. The backend
regression suite exercises repeated connection failures against a real MQTT broker.
Cancelling startup also retires sockets whose TCP connection completes during
shutdown. A real-socket regression verifies that the broker sees the connection close.

This builds `off-key-mqtt-radar:latest`. The `mqtt-radar` compose service is
build-only and never runs a container itself. Rebuild it after RADAR
dependencies or source code change.

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

### Catalogue and collection

The catalogue opens and closes from the small handle on its upper edge. Desktop
collapse restores the full content width while preserving search, navigation and
the saved panel width. On mobile the catalogue overlays the page below the header;
its edge handle, Escape or the backdrop closes it and restores focus. Ctrl/Cmd+K
opens the catalogue and focuses search in either layout.

Open **Sources** as a verified administrator to edit or import the generic
`aberration-system` catalogue: MQTT brokers, entities, topics, payload fields and
catalogue groups. Collection is explicitly opt-in; new readings start Off.
Selected numeric readings accumulate history independently of the browser and
can feed monitoring services. Temporary **Connect** previews remain in memory.

The production deployment keeps operator-managed network access and credentials
separate from exported catalogues. Local Compose can import
`dev/local/simulator-system.json` with the `mqtt-sim` profile, or
`dev/local/workshop-system.json` for a different example. See
[Collection](docs/operations/system-collection.md) for the data path and limits.

Migration `005_generic_runtime.sql` makes the generic catalogue the sole runtime.
It converts saved catalogue and monitor configuration once. Existing sensor
measurements, latest values, accounts, favourites, catalogue revisions, monitor
settings and monitoring evidence remain in place. Recording and retention keep
their existing behaviour; no separate data archive is required. Retired catalogue
APIs, provider-specific imports, old accepted-topic namespaces and the 3D
prototype are removed.

### EMQX two-node cluster mode

Enable cluster mode explicitly with the override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml up -d --build
```

This adds `emqx-worker` and updates EMQX seeds for a two-node cluster.

### Production deployment

Production infrastructure is integrated under [`infra/`](infra/README.md). Configure
GitHub's protected production environment using the [setup guide](docs/operations/github-setup.md).
After the controlled first cutover, green main runtime changes deploy automatically.

```bash
make check-infra
make deploy-prod REVISION=<full-tested-main-commit-SHA>
```

Use the [production runbook](docs/operations/production.md) and
[recovery runbook](docs/operations/recovery.md) for provisioning and recovery.

### Switching modes

When switching between local, ingress, and cluster modes, recreate resources to avoid stale
network/container DNS and namespace state:

```bash
docker compose down -v
docker network rm off-key_app-network off-key_emqx-network || true
```
