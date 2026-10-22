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
| `services` | `id` | Monitoring workload, topics, saved launch configuration, lifecycle, and operational stage |
| `deployment_maintenance` | `id` (singleton) | Durable release phase and monitor restart plan |
| `off_key_schema_migrations` | `version` | Reviewed SQL migration checksums and application times |
| `mqtt_topics` | `id` | Service-to-topic mappings |
| `favorites` | `favorite_id` | User-to-charger favourite mappings |
| `anomalies` | `(charger_id, timestamp, telemetry_type, service_id)` | Detected anomaly events and contributing sensor set |
| `monitoring_evidence` | `(service_id, timestamp, sequence_number)` | Per-inference strategy evidence used by charts and alarms |
| `anomaly_identity` | `anomaly_id` | Stable identifier mapped to an anomaly composite key |

## Relationship highlights

- `favorites.user_id → users.id`
- `favorites.charger_id → chargers.charger_id`
- `mqtt_topics.service_id → services.id`
- `anomaly_identity.(charger_id, timestamp, telemetry_type, service_id) → anomalies` composite key
- `monitoring_evidence.service_id` identifies the monitoring service that produced the inference record.

## Time-series characteristics

### Telemetry

- Indexed for charger/time and charger/type queries.
- `created` provides the ingestion-order cursor; `timestamp` is the event time.
- Used by details views, charts, and monitoring input streams.

### Anomalies

- Stores detector type, value, value semantics, and the exact contributing `sensor_set` when available.
- `anomaly_identity` gives the UI a stable deletion identifier without changing the time-series primary key.
- Monitor alarms carry their originating `service_id`, so independent monitors can
  report multivariate alarms for the same entity and timestamp. Retrying one
  monitor's result remains idempotent. The API returns this ID for exact chart
  attribution; historical and manually created events return `null`.
- Migration `007_monitor_anomaly_identity.sql` preserves existing public anomaly
  IDs in an empty legacy scope. Historical alarms lost to earlier collisions
  cannot be reconstructed automatically. Apply through the release migration
  workflow with application writers stopped. Monitor IDs are retained after
  monitor deletion, alongside their evidence and alarms.

### Monitoring evidence

- Records `strategy`, `model_type`, sensor/input timestamps, threshold, and alarm state.
- Static-baseline rows carry a conformal `p_value`; adaptive-stream rows carry an `anomaly_score`.
- E-process and restarted-martingale fields preserve tracker evidence where the selected strategy produces it.
- `tracker_results` holds additional tracker-specific results.

### Monitoring workload intent

- `services.desired_state` records whether the controller wants a worker running,
  stopped, or deleted. `lifecycle_version` fences delayed workload starts.
- The row and sensor claim commit before Docker creation. `container_id` can be
  empty during a recoverable pending creation; `launch_config`,
  `config_fingerprint` and `collection_fingerprint` identify its validated inputs.
- Reconciliation adopts matching workloads by deterministic name and verifies
  service, configuration and generation labels. Ambiguous Docker outcomes retain
  the row and claim; stop or delete persists intent before removing the worker.
- Migration `009_radar_lifecycle_intent.sql` preserves attached workers and marks
  already inactive services as stopped. Older attached workers without saved
  configuration remain observable and removable; they are not auto-created.

## Data access paths

- Frontend → API Gateway → TACTIC data services → database.
- MQTT Proxy writes telemetry through the shared backend service layer.
- RADAR writes monitoring evidence and anomalies.
- DB Sync initializes the current schema and exposes schema readiness. Startup does
  not migrate historical development schemas. An obsolete table shape fails
  readiness without rewriting existing data; use a fresh development database.
  Current tables, indexes, identity synchronization, and TimescaleDB policies are
  owned by `off_key_core.db.models` and `off_key_core.db.schema`.
- Production runs the packaged migration CLI before starting the target writers.
  Migrations and checksum records commit in one PostgreSQL transaction under a
  migration lock. See [Production deployment](../operations/production.md).

## Related pages

- [Architecture](../development/architecture.md)
- [Backend API](backend-api.md)
- [Environment variables](environment-variables.md)
