# Predictive Maintenance Platform

## Docker Compose Modes

### Local development (default)

Use the base compose file for stable local networking and host port access:

```bash
docker compose up -d --build
```

This mode runs a single EMQX node (`emqx-main`).
It uses the local mock `source-broker` for deterministic development.

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

### External ingress mode (VPN-bounded upstream MQTT pull)

This mode integrates the ingress satellite into the main project via:
- base file: `docker-compose.yml`
- ingress overlay: `docker-compose.ingress.yml`

The ingress overlay:
- starts `ingress-vpn` (Tailscale client) on `app-network`
- overrides `source-broker` to run in the VPN namespace
- configures Mosquitto bridge pull from provider-owned upstream broker

Setup:

```bash
cp .env.ingress.example .env.ingress.local
```

Fill required values in `.env.ingress.local`:
- `INGRESS_TS_AUTHKEY`
- `INGRESS_UPSTREAM_MQTT_HOST`

Run external ingress mode:

```bash
docker compose --env-file .env --env-file .env.ingress.local \
  -f docker-compose.yml -f docker-compose.ingress.yml up -d --build
```

Notes:
- local mock remains the default when ingress overlay is not used
- `mqtt-simulator` stays profile-gated and does not run unless explicitly requested
- TLS upstream mode is enabled with `INGRESS_UPSTREAM_USE_TLS=true`; set `INGRESS_UPSTREAM_TLS_INSECURE=true` only for non-production test endpoints with mismatched cert hostnames
- keep ingress secrets in local env files only; do not commit credentials

### External ingress smoke verification

Automated smoke script:

```bash
bash dev/utils/ingress_smoke_test.sh
```

Optional cleanup (stop/remove started containers after the script exits):

```bash
INGRESS_SMOKE_CLEANUP=1 bash dev/utils/ingress_smoke_test.sh
```

Optional manual sequence:

1. Start ingress mode as above.
2. Publish a test message to upstream through ingress namespace:

```bash
docker compose --env-file .env --env-file .env.ingress.local \
  -f docker-compose.yml -f docker-compose.ingress.yml \
  exec source-broker /bin/sh -ec \
  'mosquitto_pub -h "$INGRESS_UPSTREAM_MQTT_HOST" -p "${INGRESS_UPSTREAM_MQTT_PORT:-1883}" \
   -t "charger/charger-manual/live-telemetry/power" \
   -m "{\"charger_id\":\"charger-manual\",\"telemetry_type\":\"power\",\"value\":42}"'
```

3. Verify it appears on internal EMQX:

```bash
docker run --rm --network off-key_emqx-network eclipse-mosquitto:2.0 \
  mosquitto_sub -h emqx-main -p 1883 -t "charger/charger-manual/live-telemetry/power" -C 1 -W 20
```

### EMQX two-node cluster mode

Enable cluster mode explicitly with the override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml up -d --build
```

This adds `emqx-worker` and updates EMQX seeds for a two-node cluster.

### Switching modes

When switching between local, ingress, and cluster modes, recreate resources to avoid stale
network/container DNS and namespace state:

```bash
docker compose down -v
docker network rm off-key_app-network off-key_emqx-network || true
```
