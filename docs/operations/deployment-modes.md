# Deployment modes

This page documents the supported local, profile-based, cluster, and Swarm deployment patterns.

## When to use this page

Use this page when selecting or switching a run mode.

## 1. Local development — default

```bash
cp .env.example .env
docker swarm init --advertise-addr 127.0.0.1  # once; RADAR runs as Swarm services
docker compose up -d --build
```

Characteristics:

- One EMQX node: `emqx-main`.
- A local `source-broker` for deterministic development.
- `mqtt-simulator` is profile-gated. `mqtt-radar` is build-only; TACTIC launches its workloads.

Before creating a TACTIC-managed monitoring service for the first time, build its local image:

```bash
docker compose build mqtt-radar
```

## 2. Optional local profiles

=== "MQTT simulator"

    ```bash
    docker compose --profile mqtt-sim up -d --build --force-recreate mqtt-simulator
    ```

    To start the full stack with the simulator:

    ```bash
    docker compose --profile mqtt-sim up -d --build
    ```

## 3. Two-node EMQX cluster

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.override.yml \
  -f docker-compose.cluster.yml \
  up -d --build
```

This adds `emqx-worker` and cluster seed wiring for broker-cluster testing.

## 4. Production Swarm

Production uses the single authoritative model under `infra/`, released through
GitHub Actions after all main checks pass. See [GitHub setup](github-setup.md),
[Production releases](production.md), and [Recovery](recovery.md).

```bash
make check-infra                                  # validate Ansible and the rendered stack
make deploy-prod REVISION=<full-tested-main-SHA>  # dispatch Deploy Production
```

## Safe mode switching

Stop the current mode before starting another:

```bash
docker compose down
```

If containers keep resolving stale names or networks after switching between the
local, ingress and cluster modes, remove the shared networks too:

```bash
docker network rm off-key_app-network off-key_emqx-network || true
```

!!! warning
    `docker compose down -v` deletes local database and broker volumes. Use it only when a clean, destructive reset is intended.

## Mode selection guidance

| Goal | Recommended mode |
| --- | --- |
| Day-to-day development | Local default |
| Detection logic with synthetic data | Local plus `mqtt-sim` |
| Multi-node broker behaviour | Local plus cluster override |
| Production and external broker ingress | Integrated production Swarm |

## Configuration reference

Use [Environment variables](../reference/environment-variables.md) for per-mode setup.

## Related pages

- [Getting started](../getting-started.md)
- [Architecture](../development/architecture.md)
- [Testing and debugging](../development/testing-debugging.md)
