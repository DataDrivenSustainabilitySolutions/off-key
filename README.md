# Predictive Maintenance Platform

## Docker Compose Modes

### Local development (default)

Use the base compose file for stable local networking and host port access:

```bash
docker compose up -d --build
```

This mode runs a single EMQX node (`emqx-main`).

By default, anomaly detection containers are not started.
`mqtt-radar` is profile-gated and only starts when explicitly requested
or when created by the monitoring service workflow.

To run the standalone RADAR service manually:

```bash
docker compose --profile standalone-radar up -d mqtt-radar
```

### MQTT simulator profile (local only)

`mqtt-simulator` is profile-gated (`mqtt-sim`) and is intended for local synthetic
telemetry generation only.

If your base stack is already running, start/recreate only the simulator with:

```bash
docker compose --profile mqtt-sim up -d --build --force-recreate mqtt-simulator
```

If you want to start everything including simulator in one command:

```bash
docker compose --profile mqtt-sim up -d --build
```

### EMQX two-node cluster mode

Enable cluster mode explicitly with the override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml up -d --build
```

This adds `emqx-worker` and updates EMQX seeds for a two-node cluster.

### Switching modes

When switching between local and cluster modes, recreate resources to avoid stale
network/container DNS state:

```bash
docker compose down -v
docker network rm off-key_app-network off-key_emqx-network || true
```
