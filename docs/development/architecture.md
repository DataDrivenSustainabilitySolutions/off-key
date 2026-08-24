# Architecture overview

This page describes the current production-oriented architecture in the repository.

## When to use this page

Use this page to understand how services depend on one another, how data flows end to end, and where to triage failures.

## System shape

The platform runs as a Docker-based service mesh:

- `frontend` (React): user-facing UI.
- `api-gateway` (FastAPI): external API facade under `/v1`.
- `tactic-middleware` (FastAPI): data adapter and RADAR orchestration.
- `db-sync`: schema initialization and readiness API.
- `mqtt-proxy`: source MQTT ingestion and optional bridge publishing.
- `mqtt-radar`: anomaly workload, either profile-based or TACTIC-managed.
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
| MQTT Proxy | Source ingest, parsing, batching, optional forwarding | Source broker or ingress | `telemetry`, optional bridge broker | MQTT source and database |
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

1. A producer publishes `device/evCharger/<charger_id>/<telemetry_type>` to the source broker.
2. `mqtt-proxy` subscribes through `MQTT_SOURCE_TOPICS`, parses charger/type fields, and batches messages.
3. Valid observations are persisted in the `telemetry` hypertable.
4. When bridge publishing is configured, the same stream is made available to the RADAR broker.
5. Gateway telemetry endpoints expose stored data through TACTIC to frontend charts.

### 3. Monitoring lifecycle flow

1. An operator selects sensors and a strategy in the frontend.
2. The frontend calls Gateway monitor routes under `/v1/monitors`.
3. TACTIC validates the request and claims the selected sensors.
4. TACTIC creates, starts, inspects, or removes the RADAR workload through the Docker API proxy.
5. The workload runs either the static-baseline or adaptive-stream lane.
6. Runtime state and processing stages are surfaced through the Gateway.

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
5. `mqtt-proxy` at `/ready/bridge` when bridge readiness is applicable
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
| Internal checks | MQTT Proxy | `/health`, `/ready/bridge` | Ingest and bridge readiness |

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
- **Swarm:** `docker-compose.swarm.yml`
- **Swarm ingress overlay:** add `docker-compose.ingress.yml`

See [Deployment modes](../operations/deployment-modes.md) for operational commands.

## Related pages

- [Data model](../reference/data-model.md)
- [Backend API](../reference/backend-api.md)
- [Environment variables](../reference/environment-variables.md)
- [Testing and debugging](testing-debugging.md)
