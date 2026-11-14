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
| `agents` | `id` | Agents that sign in with a key: the name, a digest of the key and its last characters, what the key may start (`nothing`, `shadow` or `live`), and the member who created it. `name` is unique without regard to case. Deleting the row revokes the key |
| `chargers` | `charger_id` | Charger inventory and MQTT/connection metadata |
| `telemetry` | `(charger_id, timestamp, type)` | Observed time-series values by charger and sensor type |
| `services` | `id` | Monitoring workload, topics, saved launch configuration, lifecycle, and operational stage |
| `deployment_maintenance` | `id` (singleton) | Durable release phase and monitor restart plan |
| `off_key_schema_migrations` | `version` | The schema baseline and the reviewed SQL migrations after it, with checksums and application times |
| `mqtt_topics` | `id` | Service-to-topic mappings |
| `member_favorites` | `(user_id, kind, item_id)` | Catalogue devices, catalogue readings and monitors each member starred |
| `anomalies` | `(charger_id, timestamp, telemetry_type, service_id)` | Detected anomaly events and contributing sensor set |
| `monitoring_evidence` | `(service_id, timestamp, sequence_number)` | Per-inference strategy evidence used by charts and alarms |
| `monitoring_evidence_clock` | `id = 1` | Durable watermark serializing evidence creation times through commit, so forward cursors cannot skip late commits |
| `anomaly_identity` | `anomaly_id` | Stable identifier mapped to an anomaly composite key |
| `alarm_deletions` | `id` | Short-lived exact event selections and committed counts for confirmed, retryable bulk deletion |
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

### Pipelines and RADAR runtime

| Entity | Primary key | Purpose |
| --- | --- | --- |
| `monitoring_pipelines` | `id` | Pipeline designs and templates with their editable draft |
| `monitoring_pipeline_revisions` | `id` | Immutable compiled revisions of a pipeline |
| `monitoring_pipeline_blocks` | `id` | Named chains of steps the composer copies into a design. `name` is unique, and no design, revision or run refers to a block |
| `monitoring_pipeline_proposals` | `id` | Designs an agent or a member handed to a member to decide on: the name and the reason, the design with its layout and bindings, the author, and the decision with who made it and what they answered. It holds the design itself and no foreign key, so it reads the same after a run, a service or the agent's key is gone |
| `monitoring_pipeline_runs` | `id` | A revision bound to inputs and running as one monitoring service |
| `monitoring_pipeline_activations` | `id` | Idempotent activation requests and their phase through preflight, start and heartbeat |
| `monitoring_pipeline_run_events` | `id` | A run's lifecycle events (setup phases, stage changes, data gaps, worker crashes, end), kept after its service is purged |
| `radar_runtime_checkpoints` | `service_id` | Signed detector checkpoint for each running RADAR service |
| `radar_workloads` | `id` | What the RADAR pool runs: one row per monitor or preflight job, with its runtime, environment and memory limit, the control plane's `desired` intent, and the pool's report (`state`, the replica holding its lease and until when, attempts, exit code and the last ten crashes). A replica claims a row with a lease and runs it as a child process |

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
- `member_favorites.user_id → users.id`, removed with the member. `item_id` is a catalogue device id, a catalogue reading id or a monitor id by `kind` (`device`, `reading` or `monitor`), and is not a foreign key.
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
- `log_seq` is the row's position in the telemetry log, in commit order. Monitors
  read their streams by it and replay from the position their checkpoint saved.
- Used by details views, charts, and monitoring input streams.

### Anomalies

- Stores detector type, value, value semantics, and the exact contributing `sensor_set` when available.
- `anomaly_identity` gives the UI a stable deletion identifier without changing the time-series primary key.
- Deletion previews (`alarm_deletions`) each freeze
  the matching event IDs for ten minutes, so new arrivals cannot widen a reviewed
  selection. A successful deletion clears the IDs and retains its result for
  retries; subsequent previews remove expired records.
- Monitor alarms carry their originating `service_id`, so independent monitors can
  report multivariate alarms for the same entity and timestamp. Retrying one
  monitor's result remains idempotent. The API returns this ID for exact chart
  attribution; manually created events return `null`. Monitor IDs are retained
  after monitor deletion, alongside their evidence and alarms.

### Monitoring evidence

- Records `strategy`, `model_type`, sensor/input timestamps, threshold, and alarm state.
- Static-baseline rows carry a conformal `p_value`; adaptive-stream rows carry an `anomaly_score`.
- E-process and restarted-martingale fields preserve tracker evidence where the selected strategy produces it.
- `tracker_results` holds additional tracker-specific results.
- `detector_results` lists, for a design that combines detectors, each detector's
  `detector_id`, `score` and `surprise`; `p_value` or `anomaly_score` holds the
  combined value. It is empty for a single detector.
- `detector_inputs` lists the features each detector scored, after every step
  before it, as `{"detector_id", "inputs": {feature: value}}`. A single
  detector's entry has no `detector_id`. Values that are not finite are `null`,
  and at most 64 features per detector are kept. Charts show them as **Detector
  inputs**.
- `forecasts` lists what each forecaster step expected of the observation, as
  `{"detector_id", "target", "slot", "lead", "expected", "lower", "upper"}`.
  `target` names the feature as in `detector_inputs`, and `slot` is the reading
  it is when no step changed its values. `lower` and `upper` are the calibrated
  interval around the forecast, in the feature's units; both are `null` when the
  step has no boundary of its own. Charts draw the forecast and the interval
  around the feature in **Detector inputs**. Designs without a forecaster step
  have none.
  Each entry can additionally carry `issued`, the forecast produced after
  learning that observation: `issued_at`, `origin_step`, `origin_time`,
  `time_basis`, `step_seconds`, and up to 64 real `points`. Each point has `lead`,
  `target_step`, `target_time`, `expected`, `lower` and `upper`. Target time is
  nullable; `estimated_cadence` explicitly identifies a projection from recent
  observation timing. Only the detector's calibrated lead has bounds, using
  the boundary at issuance. `issued: null` means no new forecast was available.
- `muted` is true when the detection rule fired and a Mute alarms step kept the
  alarm from being raised; `alarm` is then false and no alarm is stored. A
  martingale tracker says the same of its own crossing as `alarm_muted` in
  `tracker_results`.

### Monitoring workload intent

- `services.desired_state` records whether the controller wants a worker running,
  stopped, or deleted. `lifecycle_version` fences delayed workload starts.
- The row and sensor claim commit before Docker creation. `container_id` can be
  empty during a recoverable pending creation; `launch_config`,
  `config_fingerprint` and `collection_fingerprint` identify its validated inputs.
- Reconciliation adopts matching workloads by deterministic name and verifies
  service, configuration and generation labels. Ambiguous Docker outcomes retain
  the row and claim; stop or delete persists intent before removing the worker.

## Data access paths

- Frontend → API (domain services in process) → database.
- The TACTIC worker reads and writes through the same services in the background.
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
