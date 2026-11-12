# Data model

This page summarizes the core persistence model used by the platform.

## When to use this page

Use this page when mapping API behaviour to persisted entities and relationships.

## Storage backbone

- Primary database: PostgreSQL with TimescaleDB.
- Time-series hypertables: `telemetry`, `anomalies`, and `monitoring_evidence`.
- `TELEMETRY_RETENTION_DAYS` controls the retention window applied to telemetry, monitoring evidence and anomalies.
- `TELEMETRY_STORAGE_CAP_GB` optionally caps telemetry and monitoring evidence storage; the oldest completed daily chunks are dropped first.

## Core entities

| Entity | Primary key | Purpose |
| --- | --- | --- |
| `users` | `id` | Identity, credentials, role, and verification state |
| `member_roles` | `id` | Named roles and the permissions each one grants |
| `chargers` | `charger_id` | Charger inventory and MQTT/connection metadata |
| `telemetry` | `(charger_id, timestamp, type)` | Observed time-series values by charger and sensor type |
| `services` | `id` | Monitoring workload, topics, saved launch configuration, lifecycle, and operational stage |
| `deployment_maintenance` | `id` (singleton) | Durable release phase and monitor restart plan |
| `off_key_schema_migrations` | `version` | Reviewed SQL migration checksums and application times |
| `mqtt_topics` | `id` | Service-to-topic mappings |
| `member_favorites` | `(user_id, kind, item_id)` | Catalogue devices, catalogue readings and monitors each member starred |
| `anomalies` | `(charger_id, timestamp, telemetry_type, service_id)` | Detected anomaly events and contributing sensor set |
| `monitoring_evidence` | `(service_id, timestamp, sequence_number)` | Per-inference strategy evidence used by charts and alarms |
| `monitoring_evidence_clock` | `id = 1` | Durable watermark serializing evidence creation times through commit, so forward cursors cannot skip late commits |
| `anomaly_identity` | `anomaly_id` | Stable identifier mapped to an anomaly composite key |
| `remembered_sessions` | `token_hash` | Rotating remember-me refresh tokens grouped by session family |
| `revoked_access_tokens` | `token_hash` | Hashed access tokens revoked at logout, retained until their expiry |

### Catalogue and collection

| Entity | Primary key | Purpose |
| --- | --- | --- |
| `system_configuration` | `id` (singleton) | Current saved catalogue document and its revision. A connection's `protocol` is `mqtt` or `http`; a reading stores `timestamp_pointer` only when it has one |
| `system_revisions` | `revision` | Every saved catalogue document, for conflict checks and history |
| `system_collection_configuration` | `id` (singleton) | Collection policy per reading plus ingress and collector status |
| `collection_state` | `(charger_id, sensor_key)` | Latest boolean, text and identifier values per reading |
| `collection_bindings` | `charger_id` | Stable mapping from a catalogue entity to its runtime charger ID |
| `collection_configuration` | `id` (singleton) | Pre-catalogue collection settings, read once by the catalogue upgrade |
| `collection_revisions` | `revision` | Pre-catalogue collection history, kept as an archive |

### Pipelines and RADAR runtime

| Entity | Primary key | Purpose |
| --- | --- | --- |
| `monitoring_pipelines` | `id` | Pipeline designs and templates with their editable draft |
| `monitoring_pipeline_revisions` | `id` | Immutable compiled revisions of a pipeline |
| `monitoring_pipeline_runs` | `id` | A revision bound to inputs and running as one monitoring service |
| `monitoring_pipeline_activations` | `id` | Idempotent activation requests and their phase through preflight, start and heartbeat |
| `monitoring_pipeline_run_events` | `id` | A run's lifecycle events (setup phases, stage changes, data gaps, worker crashes, end), kept after its service is purged |
| `radar_runtime_checkpoints` | `service_id` | Signed detector checkpoint for each running RADAR service |

### Dojo

| Entity | Primary key | Purpose |
| --- | --- | --- |
| `dojo_datasets` | `id` | A frozen dataset: name, origin (`csv` or `history`), provenance, size and time span |
| `dojo_dataset_series` | `id` | One named series of a dataset, with its unit and, for copies, the catalogue reading it came from |
| `dojo_dataset_points` | `(series_id, timestamp)` | The values; independent of `telemetry`, so retention never removes them |
| `dojo_dataset_labels` | `id` | A known problem on a dataset: an interval with a note; labels of one dataset never overlap |
| `dojo_runs` | `id` | One design replayed over one dataset: the bound configuration, status, progress, worker heartbeat and counts |
| `dojo_run_results` | `(run_id, sequence)` | One detector result of a run: time, phase, score, threshold and alarm; for a run that compares calibration methods, `method_alarms` has one bit per method that would have alarmed |

## Relationship highlights

- `users.role → member_roles.id`. `admin` (Administrator) and `user` (Member) are built in; `admin` always holds every permission, and a role cannot be deleted while a member holds it.
- `member_favorites.user_id → users.id`, removed with the member. `item_id` is a catalogue device id, a catalogue reading id or a monitor id by `kind` (`device`, `reading` or `monitor`), and is not a foreign key. Migration `023_device_favorites.sql` turned the former `entity` favourites into `device` favourites.
- `mqtt_topics.service_id → services.id`
- `anomaly_identity.(charger_id, timestamp, telemetry_type, service_id) → anomalies` composite key
- `monitoring_evidence.service_id` identifies the monitoring service that produced the inference record.
- `monitoring_pipeline_run_events.run_id → monitoring_pipeline_runs.id`; a run also keeps `final_status`, the runtime status it ended with.
- `dojo_dataset_series.dataset_id → dojo_datasets.id`, deleted with the dataset. `dojo_dataset_points.series_id` names its series without a foreign key, which would slow large imports; the Dojo service deletes points with their dataset. `dojo_datasets.created_by → users.id` is cleared when the member is removed.
- `dojo_dataset_labels.dataset_id → dojo_datasets.id`, deleted with the dataset. `dojo_dataset_labels.created_by → users.id` is cleared when the member is removed.
- `dojo_runs.dataset_id → dojo_datasets.id`, deleted with the dataset, which is refused while one of its runs waits or runs. `dojo_run_results.run_id` has no foreign key, like dataset points; the Dojo service deletes results with their run. `dojo_runs.created_by → users.id` is cleared when the member is removed.

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
- `detector_results` lists, for a design that combines detectors, each detector's
  `detector_id`, `score` and `surprise`; `p_value` or `anomaly_score` holds the
  combined value. It is empty for a single detector. Migration
  `015_detector_evidence.sql` adds the column with an empty default.
- `detector_inputs` lists the features each detector scored, after every step
  before it, as `{"detector_id", "inputs": {feature: value}}`. A single
  detector's entry has no `detector_id`. Values that are not finite are `null`,
  and at most 64 features per detector are kept. Charts show them as **Detector
  inputs**. Migration `017_detector_inputs.sql` adds the column with an empty
  default, so earlier rows have none.
- `forecasts` lists what each forecaster step expected of the observation, as
  `{"detector_id", "target", "slot", "lead", "expected", "lower", "upper"}`.
  `target` names the feature as in `detector_inputs`, and `slot` is the reading
  it is when no step changed its values. `lower` and `upper` are the calibrated
  interval around the forecast, in the feature's units; both are `null` when the
  step has no boundary of its own. Charts draw the forecast and the interval
  around the feature in **Detector inputs**. Migration
  `026_evidence_forecasts.sql` adds the column with an empty default, so
  earlier rows and designs without a forecaster step have none.

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
