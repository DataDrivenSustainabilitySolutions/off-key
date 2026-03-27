#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f ".env.ingress.local" ]]; then
  echo "Missing .env.ingress.local. Copy .env.ingress.example and fill required values."
  exit 1
fi

TOPIC="${1:-charger/charger-ingress-smoke/live-telemetry/power}"
PAYLOAD="${2:-{\"charger_id\":\"charger-ingress-smoke\",\"telemetry_type\":\"power\",\"value\":42}}"
TIMEOUT_SECONDS="${INGRESS_SMOKE_TIMEOUT_SECONDS:-20}"
CLEANUP="${INGRESS_SMOKE_CLEANUP:-0}"

COMPOSE_ARGS=(
  --env-file .env
  --env-file .env.ingress.local
  -f docker-compose.yml
  -f docker-compose.ingress.yml
)

cleanup_on_exit() {
  local exit_code=$?
  case "${CLEANUP}" in
    1|true|TRUE|yes|YES)
      echo "Cleaning up ingress smoke containers..."
      docker compose "${COMPOSE_ARGS[@]}" down --remove-orphans || true
      ;;
  esac
  return "${exit_code}"
}

trap cleanup_on_exit EXIT

echo "Starting ingress and MQTT pipeline services..."
docker compose "${COMPOSE_ARGS[@]}" up -d ingress-vpn source-broker mqtt-proxy emqx-main

echo "Waiting for mqtt-proxy bridge readiness..."
READY=0
for _ in $(seq 1 30); do
  if docker compose "${COMPOSE_ARGS[@]}" exec -T mqtt-proxy /app/bin/python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8010/ready/bridge', timeout=2)" \
    >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 2
done

if [[ "${READY}" != "1" ]]; then
  echo "mqtt-proxy bridge did not become ready in time."
  exit 1
fi

echo "Scheduling upstream publish via ingress namespace..."
(
  sleep 2
  docker compose "${COMPOSE_ARGS[@]}" exec -T \
    -e SMOKE_TOPIC="${TOPIC}" \
    -e SMOKE_PAYLOAD="${PAYLOAD}" \
    source-broker /bin/sh -ec \
    '
      if [ "${INGRESS_UPSTREAM_USE_TLS:-false}" = "true" ]; then
        if [ -n "${INGRESS_UPSTREAM_USERNAME:-}" ]; then
          : "${INGRESS_UPSTREAM_PASSWORD:?INGRESS_UPSTREAM_PASSWORD is required when username is set}"
          if [ "${INGRESS_UPSTREAM_TLS_INSECURE:-false}" = "true" ]; then
            mosquitto_pub \
              -h "$INGRESS_UPSTREAM_MQTT_HOST" \
              -p "${INGRESS_UPSTREAM_MQTT_PORT:-1883}" \
              --capath /etc/ssl/certs \
              --tls-version tlsv1.2 \
              --insecure \
              -u "$INGRESS_UPSTREAM_USERNAME" \
              -P "$INGRESS_UPSTREAM_PASSWORD" \
              -t "$SMOKE_TOPIC" \
              -m "$SMOKE_PAYLOAD"
          else
            mosquitto_pub \
              -h "$INGRESS_UPSTREAM_MQTT_HOST" \
              -p "${INGRESS_UPSTREAM_MQTT_PORT:-1883}" \
              --capath /etc/ssl/certs \
              --tls-version tlsv1.2 \
              -u "$INGRESS_UPSTREAM_USERNAME" \
              -P "$INGRESS_UPSTREAM_PASSWORD" \
              -t "$SMOKE_TOPIC" \
              -m "$SMOKE_PAYLOAD"
          fi
        else
          if [ "${INGRESS_UPSTREAM_TLS_INSECURE:-false}" = "true" ]; then
            mosquitto_pub \
              -h "$INGRESS_UPSTREAM_MQTT_HOST" \
              -p "${INGRESS_UPSTREAM_MQTT_PORT:-1883}" \
              --capath /etc/ssl/certs \
              --tls-version tlsv1.2 \
              --insecure \
              -t "$SMOKE_TOPIC" \
              -m "$SMOKE_PAYLOAD"
          else
            mosquitto_pub \
              -h "$INGRESS_UPSTREAM_MQTT_HOST" \
              -p "${INGRESS_UPSTREAM_MQTT_PORT:-1883}" \
              --capath /etc/ssl/certs \
              --tls-version tlsv1.2 \
              -t "$SMOKE_TOPIC" \
              -m "$SMOKE_PAYLOAD"
          fi
        fi
      else
        if [ -n "${INGRESS_UPSTREAM_USERNAME:-}" ]; then
          : "${INGRESS_UPSTREAM_PASSWORD:?INGRESS_UPSTREAM_PASSWORD is required when username is set}"
          mosquitto_pub \
            -h "$INGRESS_UPSTREAM_MQTT_HOST" \
            -p "${INGRESS_UPSTREAM_MQTT_PORT:-1883}" \
            -u "$INGRESS_UPSTREAM_USERNAME" \
            -P "$INGRESS_UPSTREAM_PASSWORD" \
            -t "$SMOKE_TOPIC" \
            -m "$SMOKE_PAYLOAD"
        else
          mosquitto_pub \
            -h "$INGRESS_UPSTREAM_MQTT_HOST" \
            -p "${INGRESS_UPSTREAM_MQTT_PORT:-1883}" \
            -t "$SMOKE_TOPIC" \
            -m "$SMOKE_PAYLOAD"
        fi
      fi
    '
) &
PUBLISH_PID=$!

echo "Waiting for bridged message on emqx-main topic: ${TOPIC}"
if docker compose "${COMPOSE_ARGS[@]}" exec -T \
  -e SMOKE_TOPIC="${TOPIC}" \
  -e SMOKE_TIMEOUT_SECONDS="${TIMEOUT_SECONDS}" \
  mqtt-proxy /app/bin/python -c \
  "import os, sys, time; import paho.mqtt.client as mqtt; \
topic=os.environ['SMOKE_TOPIC']; timeout=int(os.environ['SMOKE_TIMEOUT_SECONDS']); received={}; \
def on_connect(client, userdata, flags, rc, *args): \
    client.subscribe(topic, qos=0); \
def on_message(client, userdata, msg): \
    received['payload']=msg.payload.decode('utf-8', errors='ignore'); client.disconnect(); \
client=mqtt.Client(client_id='ingress-smoke-sub'); client.on_connect=on_connect; client.on_message=on_message; \
client.connect('emqx-main', 1883, 60); start=time.time(); \
while True: \
    client.loop(timeout=1.0); \
    if 'payload' in received: print(received['payload']); sys.exit(0); \
    if time.time() - start > timeout: print('timeout waiting for bridged message', file=sys.stderr); sys.exit(1)" \
  ; then
  wait "${PUBLISH_PID}"
  echo "Ingress smoke test passed."
else
  wait "${PUBLISH_PID}" || true
  echo "Ingress smoke test failed."
  exit 1
fi
