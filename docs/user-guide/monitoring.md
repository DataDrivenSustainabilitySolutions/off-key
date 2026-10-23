# User guide — monitoring

This page covers how to run anomaly-monitoring workflows for chargers.

## When to use this page

Use this page when starting, validating, or stopping monitoring workloads from the UI.

## Audience

- Operators managing anomaly-monitoring workloads.

## What monitoring does

- Starts one RADAR workload for the selected numeric readings, always as a monitoring pipeline.
- Runs either a static-baseline or adaptive-stream detection strategy.
- Persists monitoring evidence and detected anomaly records for the web app.

## Create a monitor

**Create** in the Monitoring workspace (`/?create=monitoring`) opens the
pipeline workbench described below. A reading's **Configure monitoring** link
opens it with that reading preselected.

When an operator sets `TACTIC_PIPELINE_AUTHORING_ENABLED=false` (also the
root `docker-compose.yml` fallback when `.env` omits it), Create and `/monitoring/:chargerId` show the
form-based setup instead:

1. Select one or more currently unclaimed numeric readings.
2. Choose a monitoring strategy and model.
3. Keep the defaults for a first-run validation; tune parameters only when the baseline is understood.
4. Start monitoring. The form's configuration becomes the equivalent pipeline,
   so the started service is inspected, stopped and replaced like any other.
5. Observe the service stage, monitoring evidence, and resulting anomalies.

Either way, every selected reading must already be collected as a numeric
reading in **Sources**.

## Service health and coverage

Coverage in the service overview reports known discarded observations and possible
interruptions. RADAR currently consumes a best-effort MQTT stream without a
durable replay cursor. Queue overflow, explicit throttling, invalid inputs and
connection interruptions can leave gaps. New traffic does not repair those gaps:
the monitor keeps its coverage warning even after it resumes processing. Removing
and recreating the monitor starts a new calibration and coverage history.

Throttling is disabled by default. Operators can configure a positive aggregate
limit across all of a monitor's subscribed readings; excess observations are then
counted and reported as lost monitoring coverage.

Monitoring activity separates runtime heartbeats from valid input, inference and
evidence persistence. A running detector becomes degraded if a required input is
older than the configured sensor freshness budget, scoring stops, or evidence
waits too long to commit. The service overview names missing or stale inputs and
shows the last successful inference and evidence commit. Activity recovers when
fresh inputs and scoring resume; historical coverage warnings remain visible.

## Strategy summary

| Strategy | Best suited to | Runtime behaviour |
| --- | --- | --- |
| Static baseline | Signals with a representative training/calibration period | Trains and calibrates first, then scores later observations; exposes conformal and martingale evidence |
| Adaptive stream | Signals whose behaviour should be learned continuously | Warms up, scores each observation before learning it, and adapts its preprocessing/detector state |


## Detector and alarm semantics

A static service consumes consecutive, non-overlapping phases: baseline training,
calibration, and online inference. Inference produces one conformal p-value and
feeds the same ordered stream to every configured martingale tracker. Trackers may
use `power`, `simple_mixture`, or `simple_jumper` betting and may alarm on the
all-history martingale, harmonic restarted martingale, CUSUM, or
Shiryaev-Roberts statistic. An anomaly is emitted when any tracker records a new
threshold crossing. The default is power betting with epsilon `0.5`, the
restarted statistic, and threshold `100`.

The setup form is deliberately stricter than the server on two values: it asks
for a reading freshness of at least 1 second and a betting epsilon, minimum
epsilon or jumper redistribution of at least `0.0001`. Smaller values are almost
certainly typos.

Ville thresholds on the all-history and harmonic restarted statistics retain
their anytime-valid interpretation. CUSUM and Shiryaev-Roberts thresholds are
change-detection parameters and must be calibrated for the intended null stream;
`1 / threshold` is not presented as their false-alarm probability.

Every ready-phase inference is persisted in `monitoring_evidence`, including the
p-value or score, sensor set, aggregate alarm flag, and bounded `tracker_results`
evidence for every configured martingale. Charts draw each selected alarm
statistic on a logarithmic secondary axis with its threshold. Telemetry and
evidence use the same payload event timestamp and share zoom and crosshair, so
observations from one inference stay vertically aligned; receive time is used
only when a publisher omits its event timestamp.

## Reading ownership

A reading may belong to only one active monitoring service. TACTIC serializes
claims in PostgreSQL and rejects overlapping MQTT filters, including `+` and `#`
wildcard overlap. Topic levels are literal: for example, charger IDs `charger-1`
and `charger-10` do not overlap. Stop or remove the existing service before
assigning its readings elsewhere.

## Visual monitoring pipelines

The setup page holds the service name, the entity (**Readings from**), the
**Readings to monitor** checklist and the processing graph. Its main actions are
**Load template**, **Save template** and **Apply monitoring**. Starting a
service never requires saving a template.

**Load template** offers the built-in static and adaptive starting flows plus
**Your templates**; **Manage templates** opens the shared template library.
Loading never changes the source template, and **Undo** restores the previous
flow. **Save template** stores the current graph and layout under its own
template name, independently of the service name. A concurrent edit keeps your
work and offers to save it as a new template.

Read a graph from left to right. Each card shows its role, title and underlying
operation; renaming a card helps explain its purpose while the operation name
remains visible. Ports carry their data type as a colored dot, and connections are
solid directional links in the same color, without text labels. The canvas has no
separate legend; type names appear on hover, in the inspector and in accessible
descriptions. Scores are model-specific; the static strategy's P-values come from
conformal calibration.

Drag components from **Add component** onto the canvas, or add one beside the
selected component without changing connections. Components a design can contain
only once (input, detector, decision policy and output) stay listed with a
shortcut to the existing one. The inspector switches between **Learning
settings** and **Component settings** and provides the same connection editing on
keyboards and narrow screens, listing compatible, cycle-free upstream choices.
**Locate selected component** brings its card into a readable view and **Fit
entire graph** shows the whole graph. **Arrange** lays out the graph while
preserving processing order; the magnet button (**Snap to grid**) toggles grid
snapping. Undo and redo also work with Ctrl/Cmd+Z and Shift+Ctrl/Cmd+Z outside
text fields. Click empty canvas or press Escape to release a selection before
using Delete. The validation button lists current issues; selecting one opens
that component. An unsaved setup survives a reload of the same browser tab, and
**Reset** discards it.

To keep features raw, branch from **Aligned inputs** and select the required
features. **Pass through** preserves the values at its input. **Merge features**
combines columns from the same aligned observation in the explicit input order;
rename colliding feature names before combining branches. A card title changes
presentation only; the **Rename features** component changes execution.

Unchecking readings in **Readings to monitor** changes the input slots and
bindings together; a service accepts up to 100 readings. Every slot binds a
distinct numeric reading on one entity. Labels are cosmetic; expected units
require an exact match, and unknown units remain unknown.

**Apply monitoring** validates the graph and starts the service through the same
preflight, reading claims, capacity checks and worker heartbeat as every other
start. Progress stays visible across navigation and reload: **Recover start
request** resumes an uncertain request, **Cancel start** stops it, and a failed
start offers **Return to setup**. A rejected request keeps the setup editable.

A running service always displays its bound, immutable execution. Its
arrangement can be saved independently. The live inspector shows one coherent
sampled observation, separates score and post-learning passes, and marks nodes
that did not execute. Snapshot age is visible; fresh diagnostics do not imply
persisted evidence is current. Static training appears as a batch summary.
Configuration issues and sampled runtime state have separate badges.

**Edit service** opens the running definition, layout and bindings. **Apply
changes** explains the interruption and fresh learning, then replaces the
service through the same preflight and handoff. Both sets of readings stay
reserved during preflight and handoff, and a failed preflight leaves the
predecessor running. After retirement, cancellation or failure does not silently
revive it. History remains inspectable after a service is removed. Older library,
revision and in-flight activation links still open.

Static preprocessing fits only the training window and stays frozen. Adaptive
preprocessing initializes before downstream learning; its warm-up counter counts
successful detector updates. PCA has separate centered batch and uncentered
incremental implementations. Changing online preprocessing does not transform
historical geometry already retained by the detector.

## Adaptive model selection

Adaptive monitoring uses the Aberrant release pinned by RADAR. Models are grouped by the library's
algorithm family and filtered by the number of features after preprocessing.
The original 24 numeric detectors remain available; scalar and multivariate
rolling matrix profiles add detection of unusual sequences across one or multiple
channels. Graph-event detectors and score-policy wrappers are excluded.

Warm-up and calibration are separate. The requested warm-up must satisfy the
selected model's minimum history and PCA initialization, when enabled. RADAR
validates these requirements before consuming telemetry. Calibration continues
to score before learning, freezes the higher empirical quantile, and monitoring
learns every valid observation, including anomalies.

Half-Space Trees requires features in `[0, 1]`. Selecting it chooses min-max
scaling to this range and removes projections. Values beyond previously seen
extremes are clipped before scoring. Without scaling, values outside `[0, 1]`
are rejected. The UI warns when a model has growing memory requirements.

Matrix-profile subsequences count aligned observations, not elapsed seconds.
Use consistently sampled telemetry: the sensor barrier synchronizes incoming
updates but does not resample them onto a uniform clock. Normalized profiles
compare shape independently of per-channel level and amplitude; disable
normalization when those changes should contribute to the score, taking care
that channels with larger units can dominate raw distances.

KNN exposes its FAISS window and warm-up as nested similarity-engine settings.
Existing saved model IDs and the legacy flat KNN parameters are translated on
input. Legacy histogram `max_bins` becomes `max_depth`; conflicting old and new
parameter values are rejected.

## Stop and cleanup workflow

1. Open **Monitoring** at `/` and select the service.
2. Choose **Stop and remove service** (or **Remove service** once it has stopped).
3. Confirm that the service is absent from the service list and that its readings are available again.

With the default `ephemeral` lifecycle, TACTIC also cleans up managed workloads when it restarts.

## Operational checks

```bash
curl --fail http://localhost:8000/v1/monitors/all
curl --fail http://localhost:8000/v1/monitors/models
curl --fail http://localhost:8000/v1/monitors/evidence
curl --fail http://localhost:8000/v1/anomalies/count
```

## Failure modes

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Start fails with a validation error | Invalid model parameters or sensors already claimed | Retry with defaults and check active services |
| Service runs but evidence is empty | No MQTT data flow or warm-up/calibration is incomplete | Verify the topic stream and allow the initial window to complete |
| Service disappears after a restart | Ephemeral lifecycle is configured | Use `TACTIC_RADAR_WORKLOAD_LIFECYCLE=persistent` only when persistence is required |
| Model endpoint fails | TACTIC is unreachable | Check TACTIC `/ready` and its logs |
| Evidence exists but no anomalies appear | Current observations have not crossed the detector threshold | Inspect evidence before changing model parameters |

## Telemetry persistence during outages

The MQTT proxy uses one database worker and a bounded pending batch. Database
failures retain the active batch for retry and apply backpressure to ingestion.
Shutdown attempts to drain the buffers within the configured deadline and logs
unwritten records if it cannot. These buffers are in memory, not a durable spool;
forced termination does not guarantee delivery.

## Observation time and alignment

RADAR uses a payload's `timestamp` as observation time, falling back to MQTT
receipt time when it is absent. It rejects nonfinite times, observations older
than 30 seconds, times more than 5 seconds ahead of the worker, and duplicate or
regressing timestamps for the same reading. Rejected inputs are counted as
coverage gaps and cannot refresh valid-input activity or advance the detector.
Without a source timestamp or event identity, distinct deliveries cannot be
deduplicated reliably.

An aligned vector also requires fresh receipts and observation times within
5 seconds of one another. Newer compatible readings unblock alignment; a blocked
frame never advances the model. Set `performance_config.observation_max_age_seconds`,
`observation_future_tolerance_seconds`, and `alignment_max_skew_seconds` in the
monitor API configuration to match measured source delays and sampling periods.
Standalone workers expose the corresponding `RADAR_*` environment settings.
Keep source and worker clocks synchronized. These settings form part of the
checkpoint compatibility signature; a changed alignment contract requires a new
monitor baseline.

## Related pages

- [Backend API](../reference/backend-api.md)
- [Architecture](../development/architecture.md)
- [Environment variables](../reference/environment-variables.md)
- [Testing and debugging](../development/testing-debugging.md)
- [RADAR recovery](../operations/radar-recovery.md)
- [RADAR deployment capacity](../operations/radar-capacity.md)
