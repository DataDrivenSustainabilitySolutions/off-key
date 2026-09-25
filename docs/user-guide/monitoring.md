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
