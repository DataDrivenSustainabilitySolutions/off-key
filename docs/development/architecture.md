# Architecture overview

This page describes the current production-oriented architecture in the repository.

## When to use this page

Use this page to understand how services depend on one another, how data flows end to end, and where to triage failures.

## System shape

The platform runs as a Docker-based service mesh:

Visual monitor designs, numerical compilation, activation claims and recovery
contracts are described in [Monitoring pipelines](monitoring-pipelines.md).

- `frontend` (React): user-facing UI.
- `api-gateway` (FastAPI): external API facade under `/v1`.
- `tactic-middleware` (FastAPI): data adapter and RADAR orchestration.
- `db-sync`: schema initialization and readiness API.
- `mqtt-proxy`: selected collection, sampling and accepted MQTT publishing.
- `mqtt-radar`: anomaly workload image; TACTIC launches one workload per monitor.
- `timescaledb` (PostgreSQL + TimescaleDB): operational persistence.
- `emqx-main`, plus optional `emqx-worker`: internal broker.
- `source-broker`: deterministic local source telemetry broker.
- `mailpit`: local mail capture for authentication flows.
- `socket-proxy`: restricted Docker API access for TACTIC.

## Service responsibilities and interplay

| Service | Owns | Reads from | Writes to | Critical dependencies |
| --- | --- | --- | --- | --- |
| Frontend | User workflows and UI state | API Gateway `/v1` | Browser state | API Gateway and a valid `VITE_API_URL` |
| API Gateway | External route contract and request composition | TACTIC data/orchestration endpoints | HTTP responses | TACTIC readiness |
| TACTIC | Domain data adapter and RADAR lifecycle | Database services, Docker API proxy, model registry | Database and container lifecycle | Docker API, model registry, database |
| DB Sync | Schema bootstrap and readiness | Database | Database schema | Database availability |
| MQTT Proxy | Selected admission, sampling and batching | Source-scoped raw EMQX topics | Numeric history, latest state, accepted EMQX topics | Catalog, internal EMQX and database |
| EMQX | Internal monitoring message bus | Bridge publishers | MQTT streams | Broker health and authentication settings |
| MQTT RADAR | Online anomaly detection | EMQX topics and model configuration | Monitoring evidence and anomalies | Topic stream, model initialization, database |
| TimescaleDB | Relational and time-series persistence | Write-capable services | Query results | Storage and schema readiness |

## End-to-end flows

### 1. Authentication and session flow

1. The frontend calls Gateway authentication routes under `/v1/auth`.
2. The Gateway delegates data operations to TACTIC.
3. Password hashes and verification state are resolved through database-backed services.
4. Verification and reset emails use the configured SMTP service; local mode uses Mailpit.
5. The frontend stores the bearer token and attaches it to later API calls.

### 2. Telemetry ingestion flow

1. An administrator saves MQTT broker, entity, topic and payload-field definitions through Sources.
2. Collection is explicitly enabled for chosen readings; saving definitions alone does not select them.
3. TACTIC subscribes to selected upstream topics using operator-provisioned networking and credentials, then forwards generation-scoped envelopes through internal EMQX.
4. MQTT Proxy decodes admitted readings, applies collection policy, stores numeric history/latest state and emits accepted topics.
5. RADAR consumes `telemetry/<entity>/<reading>` observations. Gateway serves stored history and live monitoring evidence to the UI.

See [Collection](../operations/system-collection.md) for revision transitions and limits.

### 3. Monitoring lifecycle flow

1. An operator selects sensors and a strategy in the frontend.
2. The frontend calls Gateway monitor routes under `/v1/monitors`.
3. TACTIC validates the request, persists the desired workload generation and
   claims its selected sensors before calling Docker. Pending and stopping
   monitors retain their sensor claims until reconciliation confirms the change.
4. TACTIC creates or adopts the deterministic `radar-<service-id>` workload.
   Reconciliation resumes interrupted creation requests and removes delayed
   creations whose intent was deleted, within the same database deployment scope.
5. A managed workload checks its persisted desired state and lifecycle version
   before starting its detector or subscribing. A delayed creation after stop or
   deletion exits without beginning monitoring. The admitted workload runs either
   the static-baseline or adaptive-stream lane.
6. Runtime state and processing stages are surfaced through the Gateway.

Reconciliation ends its database snapshot transaction before inspecting Docker
with bounded concurrency. It applies observations in short row transactions after
checking the workload generation again, preserving newer runtime heartbeats.
Stopping scales a Swarm service to zero and waits for acknowledged task shutdown
before releasing its input claim. Retiring task records are checked even if the
service was externally removed. Unknown or orphaned tasks and Docker failures
retain the claim for retry; lifecycle cleanup relies on an available Swarm
manager with authoritative task records during node recovery.

Collection changes persist stop intent and release catalogue locks while affected
workloads stop. They recheck both catalogue and collection revisions before
applying the prepared change. A concurrent edit rejects the stale change while
completed monitor stops remain durable.

### 4. Evidence and anomaly flow

1. RADAR consumes selected telemetry topics from EMQX.
2. The configured strategy calculates scores, p-values where applicable, and tracker evidence.
3. Evidence is written to `monitoring_evidence`; threshold crossings produce `anomalies` records.
4. The frontend retrieves service state, evidence, counts, and events through the Gateway.

## Startup order and readiness

The normal local startup remains one command, but dependencies become ready in this order:

1. `timescaledb`
2. `db-sync` at `/ready/schema`
3. `tactic-middleware` at `/ready`
4. `api-gateway` at `/health`
5. `mqtt-proxy` at `/ready` once the collection revision is applied
6. `frontend`

Gateway liveness can succeed while TACTIC-backed data or monitoring operations remain unavailable.

## Service-to-service HTTP contracts

| Caller | Callee | Critical paths | Purpose |
| --- | --- | --- | --- |
| Frontend | API Gateway | `/v1/auth/*`, `/v1/chargers/*`, `/v1/telemetry/*`, `/v1/monitors/*`, `/v1/anomalies*` | Primary user contract |
| API Gateway | TACTIC | `/api/v1/data/*`, `/api/v1/orchestration/radar/*`, `/api/v1/models/*` | Data access and orchestration |
| Health tooling | API Gateway | `/health` | Gateway liveness |
| Health tooling | TACTIC | `/health`, `/ready` | Orchestration and registry readiness |
| Internal checks | DB Sync | `/health`, `/ready/schema` | Schema readiness |
| Internal checks | MQTT Proxy | `/health`, `/ready` | Collection readiness |

## Failure modes and recovery checkpoints

| Symptom | Likely breakpoint | First checks |
| --- | --- | --- |
| Frontend loads but has no data | Gateway-to-TACTIC data path | Gateway health, TACTIC readiness, both logs |
| Monitoring start fails | Model validation, sensor ownership, or Docker API | TACTIC readiness, `/v1/monitors/models`, active services |
| Telemetry is missing | Source, proxy parsing, or database write | Source publish, proxy logs/readiness, database health |
| Evidence is absent | RADAR workload or broker topic path | Service list, RADAR logs, EMQX stream |
| Authentication email is missing | SMTP configuration | Mail service logs and `EMAIL_*` transport settings |

## Deployment context

- **Local default:** `docker compose up -d --build`
- **Cluster override:** `docker-compose.cluster.yml`
- **Swarm:** `infra/stack/docker-compose.swarm.yml`
- **Swarm ingress overlay:** add the integrated production ingress overlays

See [Deployment modes](../operations/deployment-modes.md) for operational commands.

## Related pages

- [Data model](../reference/data-model.md)
- [Backend API](../reference/backend-api.md)
- [Environment variables](../reference/environment-variables.md)
- [Testing and debugging](testing-debugging.md)

## Aberrant catalog integration

RADAR pins `aberrant[faiss]==1.1.0`. Shared configuration, Gateway, and TACTIC
read `off_key_core/models/adaptive_catalog.json`; they do not import NumPy,
SciPy, FAISS, or Aberrant. The snapshot is generated from the same installed
library and optional dependencies as RADAR. `models/adaptive.py` owns only the
supported-model policy, application defaults, resource limits, and compatibility
translations. Constructor schemas and default capability descriptions come
from Aberrant. Algorithm family is separate from Offkey's `adaptive_aberrant`
routing family.

After changing the dependency pin or model policy, regenerate and verify:

```bash
uv sync --project backend --all-packages --all-groups --frozen
uv run --project backend python -m off_key_mqtt_radar.catalog --write
uv run --project backend python -m off_key_mqtt_radar.catalog --check
```

CI compares the snapshot with the installed runtime, and RADAR's Docker build
runs the same check. API responses expose `catalog_id`, `algorithm_family`,
`available`, and `default_capabilities`. These capabilities describe application
**defaults**, not arbitrary edited parameters. Shared request validation checks
schemas, sensor cardinality, resource budgets, and preprocessing policy. RADAR
resolves actual capabilities, checks model/PCA warm-up, and executes constructor
validation at startup. Models needing observer-, bucket-, or graph-based
readiness cannot be added by simply editing the allowlist.

`AdaptiveStreamConfig.detector_mapping()` produces the versioned Aberrant
configuration, with a feature-schema guard first. RADAR constructs the pipeline
through `DetectorConfig`, then applies Offkey's explicit unit-interval input
policy where required. Checkpoints contain the normalized configuration,
configuration fingerprint, input keys, package version, and lifecycle state.
Signed atomic checkpoint I/O remains owned by Offkey. Runtime model information
includes the resolved model identity and capabilities.

Integrated production releases seed the tested RADAR image on backend nodes, stop
active workers and restart their saved configurations under new UUIDs with fresh
calibration. The production workflow verifies them before completing the release.
Adaptive configuration carries its expected Aberrant version to reject mixed
versions. Cross-version model pickles are incompatible: preserve them for a
rollback, but allow the upgraded monitors to warm up and calibrate afresh.
Validate the image and the opt-in `test_adaptive_lane_e2e.py` flow against a
non-production MQTT/PostgreSQL stack before deploying.
