# Data model

This page summarizes the core persistence model used by the platform.

## When to use this page

Use this page when mapping API behaviour to persisted entities and relationships.

## Storage backbone

- Primary database: PostgreSQL with TimescaleDB.
- Time-series hypertables: `telemetry`, `anomalies`, and `monitoring_evidence`.
- `TELEMETRY_RETENTION_DAYS` controls the retention window applied to telemetry and monitoring evidence.

## Core entities

| Entity | Primary key | Purpose |
| --- | --- | --- |
| `users` | `id` | Identity, credentials, role, and verification state |
| `chargers` | `charger_id` | Charger inventory and MQTT/connection metadata |
| `telemetry` | `(charger_id, timestamp, type)` | Observed time-series values by charger and sensor type |
| `services` | `id` | Monitoring workload, topics, lifecycle, and operational stage |
| `mqtt_topics` | `id` | Service-to-topic mappings |
| `favorites` | `favorite_id` | User-to-charger favourite mappings |
| `anomalies` | `(charger_id, timestamp, telemetry_type)` | Detected anomaly events and contributing sensor set |
| `monitoring_evidence` | `(service_id, timestamp, sequence_number)` | Per-inference strategy evidence used by charts and alarms |
| `anomaly_identity` | `anomaly_id` | Stable identifier mapped to an anomaly composite key |
| `model_registry` | `id` | Active model definitions, import paths, schemas, and defaults |

## Relationship highlights

- `favorites.user_id → users.id`
- `favorites.charger_id → chargers.charger_id`
- `mqtt_topics.service_id → services.id`
- `anomaly_identity.(charger_id, timestamp, telemetry_type) → anomalies` composite key
- `monitoring_evidence.service_id` identifies the monitoring service that produced the inference record.

## Time-series characteristics

### Telemetry

- Indexed for charger/time and charger/type queries.
- `created` provides the ingestion-order cursor; `timestamp` is the event time.
- Used by details views, charts, and monitoring input streams.

### Anomalies

- Stores detector type, value, value semantics, and the exact contributing `sensor_set` when available.
- `anomaly_identity` gives the UI a stable deletion identifier without changing the time-series primary key.

### Monitoring evidence

- Records `strategy`, `model_type`, sensor/input timestamps, threshold, and alarm state.
- Static-baseline rows carry a conformal `p_value`; adaptive-stream rows carry an `anomaly_score`.
- E-process and restarted-martingale fields preserve tracker evidence where the selected strategy produces it.
- `tracker_results` holds additional tracker-specific results.

## Model registry

`model_registry` is the database-backed source for model discovery:

- model metadata and family
- import paths
- JSON parameter schema and defaults
- version and activation state

TACTIC and the Gateway monitoring endpoints use these definitions for discovery and validation.

## Data access paths

- Frontend → API Gateway → TACTIC data services → database.
- MQTT Proxy writes telemetry through the shared backend service layer.
- RADAR writes monitoring evidence and anomalies.
- DB Sync initializes the schema and exposes schema readiness.

## Related pages

- [Architecture](../development/architecture.md)
- [Backend API](backend-api.md)
- [Environment variables](environment-variables.md)
