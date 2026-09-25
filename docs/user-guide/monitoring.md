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

### Strategy summary

| Strategy | Best suited to | Runtime behaviour |
| --- | --- | --- |
| Static baseline | Signals with a representative training/calibration period | Trains and calibrates first, then scores later observations; exposes conformal and martingale evidence |
| Adaptive stream | Signals whose behaviour should be learned continuously | Warms up, scores each observation before learning it, and adapts its preprocessing/detector state |

## Adaptive model selection

Adaptive monitoring uses Aberrant 1.1.0. Models are grouped by the library's
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

## Telemetry persistence during outages

The MQTT proxy uses one database worker and a bounded pending batch. Database
failures retain the active batch for retry and apply backpressure to ingestion.
Shutdown attempts to drain the buffers within the configured deadline and logs
unwritten records if it cannot. These buffers are in memory, not a durable spool;
forced termination does not guarantee delivery.
