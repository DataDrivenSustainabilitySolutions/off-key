# Testing and debugging

This page is the operational test and triage playbook for the current stack.

## When to use this page

Use this page when validating local changes, checking runtime health, or diagnosing user-facing failures across API, telemetry, and monitoring.

## Audience

- Developers debugging service behaviour.
- Operators triaging local or cluster-like environments.

## Test commands

### Backend

```bash
uv run --project backend ruff check .
uv run --project backend python -m pytest -q
```

Expected result: lint exits with status `0`, and tests complete without failures.

### Frontend

```bash
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

Expected result: no lint errors, passing tests, and a successful production build.

### Repository pre-commit gate

```bash
uv run --project backend pre-commit run --all-files
```

## Runtime health checks

=== "Host endpoints"

    ```bash
    curl --fail http://localhost:8000/health
    curl --fail http://localhost:8001/health
    curl --fail http://localhost:8001/ready
    ```

=== "Internal endpoints"

    ```bash
    docker compose exec mqtt-proxy wget -qO- http://localhost:8010/health
    docker compose exec mqtt-proxy wget -qO- http://localhost:8010/ready
    docker compose exec mqtt-proxy wget -qO- http://localhost:8010/ready/bridge
    docker compose exec db-sync wget -qO- http://localhost:8009/health
    docker compose exec db-sync wget -qO- http://localhost:8009/ready/schema
    ```

`/ready/bridge` reflects the configured bridge mode; a disabled bridge is not the same as a broken ingestion service.

## Log inspection

Tail critical services:

```bash
docker compose logs -f api-gateway tactic-middleware db-sync mqtt-proxy mqtt-radar
```

Inspect recent output for one service:

```bash
docker compose logs --tail 200 tactic-middleware
```

## Debug flows by symptom

### Frontend loads but charger data is empty

1. Confirm that `VITE_API_URL` is reachable from the frontend runtime.
2. Check Gateway liveness at <http://localhost:8000/health>.
3. Check TACTIC readiness at <http://localhost:8001/ready>.
4. Inspect Gateway and TACTIC logs for the upstream error.

### Monitoring start fails

1. Confirm that the model registry is populated:

    ```bash
    curl --fail http://localhost:8000/v1/monitors/models
    ```

2. List existing services and look for sensors already claimed:

    ```bash
    curl --fail http://localhost:8000/v1/monitors/all
    ```

3. Confirm TACTIC readiness.
4. Inspect TACTIC logs for validation, Docker API, image, or network failures.

### Telemetry is not arriving

1. Verify that the source publisher or simulator is active.
2. Confirm that its topic matches `device/evCharger/<charger_id>/<telemetry_type>` and the `MQTT_SOURCE_TOPICS` filter.
3. Check proxy health and readiness.
4. Inspect proxy logs for parsing, authentication, or database-write errors.
5. Query the Gateway telemetry endpoint.

### Evidence or anomalies are missing

1. Verify that the monitor workload exists.
2. Confirm that data reaches its EMQX topic.
3. Allow static calibration or adaptive warm-up to complete.
4. Query evidence and anomaly counts:

    ```bash
    curl --fail "http://localhost:8000/v1/monitors/evidence?charger_id=<charger-id>"
    curl --fail http://localhost:8000/v1/anomalies/count
    ```

5. Inspect RADAR logs for model or persistence errors.

## Service addresses — local default

| Component | Address or port |
| --- | --- |
| Frontend | `5173` |
| API Gateway | `8000` |
| TACTIC | `8001` |
| DB Sync | Internal `8009` |
| MQTT Proxy health | Internal `8010` |
| PostgreSQL/TimescaleDB | `5432` |
| EMQX MQTT | `1883` |
| Source broker MQTT | `1884`, host loopback |
| EMQX dashboard | `18083` |
| Mailpit UI / SMTP | `8025` / `1025` |

## Related pages

- [Getting started](../getting-started.md)
- [Developer setup](setup.md)
- [Environment variables](../reference/environment-variables.md)
- [Deployment modes](../operations/deployment-modes.md)
- [Backend API](../reference/backend-api.md)
