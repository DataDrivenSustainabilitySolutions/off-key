# User guide — monitoring

This page covers how to run anomaly-monitoring workflows for chargers.

## When to use this page

Use this page when starting, validating, or stopping monitoring workloads from the UI.

## Audience

- Operators managing anomaly-monitoring workloads.

## What monitoring does

- Creates a RADAR workload for selected MQTT sensor topics.
- Runs either a static-baseline or adaptive-stream detection strategy.
- Persists monitoring evidence and detected anomaly records for the web app.

!!! important
    A sensor can be owned by only one active monitoring service. Stop or remove the existing service before assigning that sensor elsewhere.

## Standard workflow

1. Open `/monitoring/:chargerId`.
2. Select one or more currently unclaimed telemetry sensors.
3. Choose a monitoring strategy and model.
4. Keep the defaults for a first-run validation; tune parameters only when the baseline is understood.
5. Start monitoring.
6. Observe the service stage, monitoring evidence, and resulting anomalies.

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

### Strategy summary

| Strategy | Best suited to | Runtime behaviour |
| --- | --- | --- |
| Static baseline | Signals with a representative training/calibration period | Trains and calibrates first, then scores later observations; exposes conformal and martingale evidence |
| Adaptive stream | Signals whose behaviour should be learned continuously | Warms up, scores each observation before learning it, and adapts its preprocessing/detector state |

## Visual monitoring pipelines

When visual pipeline authoring is enabled, the Monitoring workspace provides a
shared pipeline library. Administrators create designs from a static or adaptive
template, arrange and configure their components, then save a draft. Publishing
creates a revision. Activation separately reviews input bindings and any service
being replaced. Members can inspect published designs and running services.

Read a graph from left to right. Each card shows its role, title, underlying
operation and input/output data types. Renaming a card helps explain its purpose;
the operation name remains visible. Connections have arrows, labels and line
patterns for features, scores, P-values and decisions. Scores are model-specific;
the static strategy's P-values come from conformal calibration.

Use **Selected component** to navigate a larger graph, then **Locate selected
component** to bring its card into a readable view. Fit view returns to the full
graph. The inspector provides the same connection editing on keyboards and narrow
screens. It lists compatible, cycle-free upstream choices. **Arrange** changes
positions while preserving processing order.

To keep features raw, branch from **Aligned inputs** and select the required
features. **Pass through** preserves the values at its input. **Merge features**
combines columns from the same aligned observation in the explicit input order;
rename colliding feature names before combining branches.

Configuration issues appear on the affected cards. A running revision shows
separate sampled runtime badges; check snapshot age, readiness and coverage in
its diagnostics. In an adaptive graph, preprocessing initialization and detector
warm-up are separate. Warm-up counts successful detector learning updates.

Editing a running service opens a reusable draft. Saving or publishing that draft
leaves the running revision active until an explicit activation replaces it.

## Adaptive model selection

Adaptive monitoring uses Aberrant 1.3.0. Models are grouped by the library's
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

## Visual pipeline designs

When visual authoring is enabled, **Create** opens the monitoring workbench
directly. Drag components from the left toolbox onto the canvas and connect their
typed ports. The right inspector switches between **Service settings** (name,
entity, input slots and learning settings) and **Component settings**. On narrow
screens, the panel buttons expose the same tools.

The optional **Templates** menu loads a static or adaptive starting flow, or a
saved design. A published design loads its latest immutable revision; an
unpublished design loads its saved draft. Changes apply to your own copy, and
**Undo** restores the previous flow. **Manage saved designs** in that menu opens
the shared library; returning preserves your workbench. Opening Create and loading
templates save nothing until **Save draft**. If the operator has disabled visual
authoring, Create continues to use the form-based setup.

The canvas has a subtle blueprint grid. Dropped and moved components snap to it
by default. Use the magnet button (**Snap to grid**) for free placement; the grid
texture stays visible. Changing this setting preserves existing arrangements.
**Arrange** lays out the graph explicitly; manual arrangement is preserved.
The node list and connection menus
provide the same editing operations on a keyboard or narrow screen.

Select input slots by stable identity. Bind every slot to a distinct enabled
numeric reading on one entity during activation review. Labels are cosmetic;
expected units require an exact match, and unknown units remain unknown. Suggested
bindings must be reviewed. Use selection to split features into branches, renaming
to avoid collisions, and ordered merge connections to join them again. **Node
title** changes presentation; the **Rename features** component changes execution.

**Save draft** saves shared work without changing a running monitor. **Publish
revision** validates and creates an immutable executable revision. **Start revision**
or **Review replacement** reviews bindings, executable changes, predecessor and
fresh training/calibration before activation. An existing draft is never silently
overwritten when editing a running revision. Concurrent saves offer reload or
save as copy. **Activate replacement** confirms the reviewed handoff.

A running monitor always displays its bound immutable revision. Its arrangement
can be saved independently. The live inspector shows one coherent sampled
observation, separates score and post-learning passes, and marks nodes that did
not execute. Snapshot age is visible; fresh diagnostics do not imply persisted
evidence is current. Static training appears as a batch summary.

Static preprocessing fits only the training window and stays frozen. Adaptive
preprocessing initializes before downstream learning; its warm-up counter counts
successful detector updates. PCA has separate centered batch and uncentered
incremental implementations. Changing online preprocessing does not transform
historical geometry already retained by the detector.

Replacement reserves both sets of inputs during preflight and handoff. A failed
preflight leaves the predecessor running. After retirement, cancellation or failure
does not silently revive it. Reusing an earlier revision starts a fresh run.
History remains inspectable after a service is removed.

## Stop and cleanup workflow

1. Open the charger monitoring view or `/services`.
2. Stop or remove the active service.
3. Confirm that the service is absent from the service list and that its sensors are available again.

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
| Model endpoint is empty | Model registry has not initialized | Check TACTIC `/ready` and its logs |
| Evidence exists but no anomalies appear | Current observations have not crossed the detector threshold | Inspect evidence before changing model parameters |

## Related pages

- [Backend API](../reference/backend-api.md)
- [Architecture](../development/architecture.md)
- [Environment variables](../reference/environment-variables.md)
- [Testing and debugging](../development/testing-debugging.md)
- [RADAR recovery](../operations/radar-recovery.md)
- [RADAR deployment capacity](../operations/radar-capacity.md)

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
