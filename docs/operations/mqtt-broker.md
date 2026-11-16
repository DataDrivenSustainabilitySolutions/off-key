# Internal MQTT broker

off-key's internal message bus is [Eclipse Mosquitto](https://mosquitto.org/)
2.1, licensed under the EPL-2.0 and EDL-1.0.

The broker carries only off-key's own traffic: TACTIC ingress publishes each
selected reading as a retained QoS 1 envelope, the MQTT proxy subscribes to those
envelopes and publishes accepted telemetry topics. Sources never connect to it.

## What runs where

| Stack | Service | Listener | Logins | State |
| --- | --- | --- | --- | --- |
| Production and demo Swarm | `mosquitto` on `mqtt-network` | TLS on 8883 | `offkey-proxy`, `offkey-radar` | `mosquitto_data` volume |
| Demo's public source feed | `demo-broker` | Plain 1883 on an internal overlay | Anonymous | None |
| `docker compose` and `dev/local` | `mosquitto` | Plain 1883 on the private network | Anonymous | Compose volume |
| CI `collection` job | `mosquitto` | Plain 1883 on loopback | Anonymous | None |

Clients dial the service name, `mosquitto` (`mqtt_broker_host`,
`tactic_radar_default_mqtt_broker_host`), which is also the DNS name in the broker
certificate.

The production configuration is `infra/stack/mosquitto.conf`. Every release
renders the password file from `mqtt_proxy_password` and `mqtt_radar_password`
in the vault, hashed in Mosquitto's `sha512-pbkdf2` format, and mounts it with the
TLS certificate and key as Swarm secrets that only the broker's user (uid 1883)
can read. A password changed in the vault therefore reaches the broker and its
client in the same release.

Mosquitto keeps retained snapshots in memory and writes `mosquitto.db` every
minute, on shutdown and on `SIGUSR1`. Clients use clean sessions, so the
snapshots are the broker's only state. Backups and restores use the usual
`SERVICES=postgres,mosquitto` tools in [Recovery](recovery.md).

## Certificate

`infra/scripts/generate-mqtt-pki.sh` creates a CA and a broker certificate for
`DNS:mosquitto`. Put `ca.crt`, `broker.crt` and `broker.key` in the vault as
`mqtt_ca_cert`, `mqtt_server_cert` and `mqtt_server_key`; keep the encrypted
`ca.key` offline. A release checks the chain and the name before it changes the
stack.

## Updates

Dependabot proposes Mosquitto tags for the Compose files. The production version
is the `mosquitto` digest in `infra/ansible/inventories/prod/group_vars/all/release.yml`;
`infra/tests/test_platform_pins.py` fails when a local stack or the `collection`
job runs a different one. Source broker fixtures (`source-broker`, the
`fixture-broker-*` services) stand in for third-party brokers and keep their own
version.

## Switching a stack from EMQX

This is a clean break: nothing is migrated and there is no way back to EMQX.

Before the first release with Mosquitto, in both the production and the demo
vault:

1. Generate a new certificate with `infra/scripts/generate-mqtt-pki.sh`.
2. Store it as `mqtt_ca_cert`, `mqtt_server_cert` and `mqtt_server_key`, and remove
   `emqx_ca_cert`, `emqx_server_cert`, `emqx_server_key`,
   `emqx_dashboard_password` and `emqx_node_cookie`.

A release without the new keys stops at its vault checks before it changes the
stack.

The release then removes the `emqx-main` service (`stack_replaced_services`),
starts `mosquitto` with an empty volume on the new `mqtt-network`, and waits for
the MQTT proxy to connect. Retained snapshots start empty and return with each
reading's next value; history in the database is unaffected.

Afterwards, on the backend node:

- `docker volume rm off-key_emqx_data off-key_emqx_log` (and the `off-key-demo_`
  ones), and `docker network rm off-key_emqx-network off-key-demo_emqx-network`.
- `docker service ls --filter label=managed_by=tactic` should list nothing; remove
  any older RADAR worker it shows.
- Remove the `emqx.` public hostname from the Cloudflare tunnel.

## Rehearsal

The switch was rehearsed in a single-node Swarm with the broker service rendered
by the production playbook, a real CA and broker certificate from
`generate-mqtt-pki.sh`, and a Paho client verifying TLS.

| Step | Result |
| --- | --- |
| Switch from EMQX | 16 s without a broker; login accepted, wrong password and anonymous refused, no permission warnings |
| Backup (`backup_mosquitto.yml`) | 7 s, manifest with `mosquitto.db` |
| Restore (`restore-stack-state.yml`, `SERVICES=mosquitto`) | A message changed after the backup reads its backed-up value again |
| Password rotation | New password accepted, old refused, retained snapshots kept |
| Demo `demo-broker` config | Healthcheck passes, no warnings |
