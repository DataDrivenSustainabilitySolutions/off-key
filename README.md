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

### External ingress mode (Swarm — Tailscale VPN + EMQX bridge)

Ingress is a Swarm-only overlay. It adds two services to the stack:
- `tailscale-vpn` — Tailscale in userspace mode, exposes a SOCKS5 proxy on `:1055`
- `mqtt-tailscale-bridge` — gost TCP forwarder: EMQX connects here on `:1883`, traffic is tunnelled through the Tailscale SOCKS5 proxy to the vendor broker using MagicDNS

No Linux capabilities are required. There is no intermediate Mosquitto broker.
Auth, TLS, and topic subscriptions are configured in the EMQX bridge (Data Integration → Bridges), not in this compose file.

Setup:

```bash
cp .env.ingress.example .env.ingress.local
```

Fill required values in `.env.ingress.local`:
- `INGRESS_UPSTREAM_MQTT_HOST` — `.ts.net` MagicDNS hostname of the vendor broker
- `INGRESS_TS_AUTHKEY` — required for first login; optional after state is pre-seeded

Pre-flight on every backend node:

```bash
mkdir -p /opt/stacks/off-key/tailscale-ingress-state
# Optionally copy tailscaled.state from a pre-authenticated installation:
# scp tailscaled.state <node>:/opt/stacks/off-key/tailscale-ingress-state/
```

Deploy:

```bash
docker stack deploy \
  --env-file .env.ingress.local \
  -c docker-compose.swarm.yml \
  -c docker-compose.ingress.yml \
  off-key
```

After deploy, create an EMQX MQTT bridge (EMQX dashboard → Data Integration → Bridges):
- Server: `mqtt-tailscale-bridge:1883`
- Set upstream credentials, TLS, and topic subscriptions there

Notes:
- local mock `source-broker` remains the default for local dev; ingress is Swarm-only
- keep ingress secrets in local env files only; do not commit credentials

### External ingress smoke verification

After deploy, verify the bridge is passing traffic:

```bash
# Subscribe to a charger topic via the internal EMQX node
docker run --rm --network off-key_emqx-network eclipse-mosquitto:2.0 \
  mosquitto_sub -h emqx-main -p 1883 -t "charger/+/live-telemetry/#" -C 1 -W 30
```

If the EMQX bridge is connected and the vendor device is publishing, a message should arrive within the timeout. If not, check:

```bash
# Tailscale status inside the VPN container
docker exec $(docker ps -q -f name=off-key_tailscale-vpn) tailscale status

# gost bridge logs
docker service logs off-key_mqtt-tailscale-bridge
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
