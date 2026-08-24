# Deployment modes

This page documents the supported local, profile-based, cluster, and Swarm deployment patterns.

## When to use this page

Use this page when selecting or switching a run mode.

## 1. Local development — default

```bash
cp .env.example .env
docker compose up -d --build
```

Characteristics:

- One EMQX node: `emqx-main`.
- A local `source-broker` for deterministic development.
- `mqtt-radar` and `mqtt-simulator` are profile-gated.

Before creating a TACTIC-managed monitoring service for the first time, build its local image:

```bash
docker compose build mqtt-radar
```

## 2. Optional local profiles

=== "Standalone RADAR"

    ```bash
    docker compose --profile standalone-radar up -d mqtt-radar
    ```

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
  -f docker-compose.cluster.yml \
  up -d --build
```

This adds `emqx-worker` and cluster seed wiring for broker-cluster testing.

## 4. Swarm — base

Docker Swarm does not apply Compose `.env` substitution during `docker stack deploy`. Render the file first:

```bash
docker compose \
  --env-file .env \
  -f docker-compose.swarm.yml \
  config \
  | docker stack deploy --with-registry-auth -c - off-key
```

Pin the `*_IMAGE` variables in `.env` to immutable release tags before a deployment.

## 5. Swarm ingress overlay — Tailscale and gost

1. Copy the ingress template:

    ```bash
    cp .env.ingress.example .env.ingress.local
    ```

2. Provide the required upstream host, authentication, and state-directory values.
3. Ensure the host state directory exists on the target backend node.
4. Render both Compose files and deploy:

    ```bash
    docker compose \
      --env-file .env \
      --env-file .env.ingress.local \
      -f docker-compose.swarm.yml \
      -f docker-compose.ingress.yml \
      config \
      | docker stack deploy --with-registry-auth -c - off-key
    ```

5. In EMQX, configure an MQTT bridge to `mqtt-tailscale-bridge:1883` with the upstream authentication and TLS settings.
6. Subscribe to `device/#` and republish `${topic}`, `${payload}`, and `${qos}` unchanged.

The bridge must preserve topics in the form `device/evCharger/<charger_id>/<telemetry_type>`.

## Safe mode switching

Stop the current mode before starting another:

```bash
docker compose down
```

!!! warning
    `docker compose down -v` deletes local database and broker volumes. Use it only when a clean, destructive reset is intended.

## Mode selection guidance

| Goal | Recommended mode |
| --- | --- |
| Day-to-day development | Local default |
| Detection logic with synthetic data | Local plus `mqtt-sim` |
| Multi-node broker behaviour | Local plus cluster override |
| VPN ingress from an external broker | Swarm plus ingress overlay |

## Configuration reference

Use [Environment variables](../reference/environment-variables.md) for per-mode setup.

## Related pages

- [Getting started](../getting-started.md)
- [Architecture](../development/architecture.md)
- [Testing and debugging](../development/testing-debugging.md)
