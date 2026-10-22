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

### RADAR production integration

The [RADAR production integration workflow](../../.github/workflows/radar-production-integration.yml)
runs on pull requests, main, merge queues and manual dispatch. It builds the
current production `backend/Dockerfile`, uses Python 3.14 and frozen dependencies,
and selects the TimescaleDB image pinned by the production release manifest.
Its isolated Ubuntu runner initializes Swarm, runs real MQTT/database/task
replacement regressions and cleans labelled fixtures within a 30 minute job.
Production release selection requires a successful main-push run for the same
commit, alongside the other release workflows.

Main also requires this check before merging, bound to GitHub Actions. The dedicated
job requires a nonempty JUnit report with zero skipped cases. Missing integration
prerequisites therefore fail that job; the general backend suite still supports
optional integration skips for local development.

To reproduce on a dedicated local Docker engine, initialize Swarm and provide a
disposable PostgreSQL server whose test role can create and drop databases. Set
its host URL in `TEST_SCHEMA_DATABASE_URL`; tests create uniquely named databases.
The workflow contains the server bootstrap and readiness commands. Then run:

```bash
uv sync --project backend --all-packages --all-groups --frozen --python 3.14
export TEST_RADAR_DATABASE_IMAGE="$(python3 -c 'import json; print(json.load(open("infra/ansible/inventories/prod/group_vars/all/release.yml"))["release"]["images"]["postgres"])')"
export TEST_RADAR_SWARM_IMAGE=off-key-radar-integration:local
export TEST_RADAR_DOCKER=1
docker pull eclipse-mosquitto:2.0
docker build -f backend/Dockerfile -t "$TEST_RADAR_SWARM_IMAGE" \
  --build-arg SERVICE_NAME=off-key-mqtt-radar \
  --build-arg SERVICE_ROOT=services/mqtt/radar backend
uv run --frozen --project backend python -m pytest -q --tb=short \
  backend/tests/test_radar_mqtt_integration.py \
  backend/tests/test_monitor_anomaly_identity_integration.py \
  backend/tests/test_radar_runtime_checkpoints.py \
  backend/tests/test_radar_checkpoint_ownership.py \
  backend/tests/test_radar_lifecycle_integration.py \
  backend/tests/test_radar_activity_integration.py \
  backend/tests/test_radar_bounded_runtime.py \
  backend/tests/test_radar_resource_budget.py \
  backend/tests/test_radar_observation_integration.py \
  backend/tests/test_radar_observation_recovery.py \
  backend/tests/test_radar_swarm_integration.py
```

The two opt-in variables enable actual Docker lifecycle tests and current-image
Swarm tests. These cover reconnect and ACL failures, scoped alarms, signed
checkpoint recovery, overload, sensor silence, interrupted creation, concurrent
heartbeats/catalogue changes, task shutdown, resource admission and observation
time validation. Fixture teardown removes only resources owned by each run.

### Frontend

```bash
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

Expected result: no lint errors, passing tests, and a successful production build.

CI browser journeys retain one retry for diagnostic evidence. Any test that passes
only on retry is classified as flaky and fails CI.

The member-management browser journeys read invitation links from the local mail
sink. Set `MAILPIT_BASE_URL` to its reachable HTTP endpoint when using custom ports.
The disposable production Swarm rehearsal publishes its SMTP fixture's API on
port `8025` and supplies `MAILPIT_BASE_URL=http://127.0.0.1:8025` in `smoke.env`.

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
    docker compose exec db-sync wget -qO- http://localhost:8009/health
    docker compose exec db-sync wget -qO- http://localhost:8009/ready/schema
    ```

`/ready` reports an applied collection revision. An empty selection is healthy idle.

## Log inspection

Tail critical services:

```bash
docker compose logs -f api-gateway tactic-middleware db-sync mqtt-proxy
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
2. Check the Sources catalog, selected sensors, matching applied revisions and per-broker connection status.
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
