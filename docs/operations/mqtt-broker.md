# Internal MQTT broker

off-key's internal message bus is [Eclipse Mosquitto](https://mosquitto.org/)
2.1, licensed under the EPL-2.0 and EDL-1.0. It replaced EMQX, whose releases
from 5.9 on are under the Business Source License 1.1 rather than an open-source
licence; 5.8.9, the last open-source EMQX, gets no further fixes.

The broker carries only off-key's own traffic: TACTIC ingress publishes each
selected reading as a retained QoS 1 envelope, the MQTT proxy subscribes to those
envelopes and publishes accepted telemetry topics. Sources never connect to it.

## What runs where

| Stack | Service | Listener | Logins | State |
| --- | --- | --- | --- | --- |
| Production and demo Swarm | `mosquitto` | TLS on 8883 | `offkey-proxy`, `offkey-radar` | `mosquitto_data` volume |
| Demo's public source feed | `demo-broker` | Plain 1883 on an internal overlay | Anonymous | None |
| `docker compose` and `dev/local` | `mosquitto` | Plain 1883 on the private network | Anonymous | Compose volume |
| CI `collection` job | `mosquitto` | Plain 1883 on loopback | Anonymous | None |

The production configuration is `infra/stack/mosquitto.conf`. Every release
renders the password file from `mqtt_proxy_password` and `mqtt_radar_password`
in the vault, hashed in Mosquitto's `sha512-pbkdf2` format, and mounts it with the
TLS certificate and key as Swarm secrets that only the broker's user (uid 1883)
can read. A password changed in the vault therefore reaches the broker and its
client in the same release; there is no separate broker user to rotate first.

Mosquitto keeps retained snapshots in memory and writes `mosquitto.db` every
minute, on shutdown and on `SIGUSR1`. Clients use clean sessions, so the
snapshots are the broker's only state.

## Names kept from EMQX

Three names still say EMQX. Each is an identity something else depends on, so
renaming it is a separate change:

- **`emqx-main`** is the DNS name in the broker certificate and the address every
  client dials (`mqtt_broker_host`, `tactic_radar_default_mqtt_broker_host`). The
  `mosquitto` service answers on it as a network alias. Renaming it needs a new
  certificate from `infra/scripts/generate-mqtt-pki.sh`.
- **`emqx-network`** is the overlay that TACTIC's runtime workers join and that
  log collection uses to find older RADAR workers.
- **`emqx_ca_cert`, `emqx_server_cert`, `emqx_server_key`** are the vault keys of
  the TLS material, so no vault edit is needed for the move.

`emqx_dashboard_password` and `emqx_node_cookie` are no longer read. Keep them in
the vault while a rollback to an EMQX release is possible, because those releases
require them.

## Updates

Dependabot proposes Mosquitto tags for the Compose files. The production version
is the `mosquitto` digest in `infra/ansible/inventories/prod/group_vars/all/release.yml`;
`infra/tests/test_platform_pins.py` fails when a local stack or the `collection`
job runs a different one. Source broker fixtures (`source-broker`, the
`fixture-broker-*` services) stand in for third-party brokers and keep their own
version.

## Moving a stack from EMQX to Mosquitto

The first release with Mosquitto makes the move on its own, for production and
the demo alike:

1. `stack_replaced_services` lists `emqx-main`, so the release stops and removes
   the EMQX service before it submits the new model. Both brokers answer on
   `emqx-main`, so they never run together.
2. `docker stack deploy` starts `mosquitto` with an empty `mosquitto_data` volume.
   It is a new service, not a persistence change, so no backup or confirmation is
   asked for.
3. Clients reconnect to the same name, certificate and passwords. The demo's
   `demo-broker` keeps its name and switches image in place.
4. The release's own readiness checks need the MQTT proxy connected and its
   collection revision applied, so a broker that rejects TLS or a login fails the
   release before the browser bundle changes.

EMQX's volumes, `<stack>_emqx_data` and `<stack>_emqx_log`, stay on the backend
node untouched; they are the rollback.

Retained snapshots are not copied. Each selected reading's latest state returns
with its next value, and history and latest state in the database are
unaffected. The broker is unavailable between the two services, about 15 to 20
seconds in the rehearsal below; clients reconnect with backoff.

Before the release:

- Take a backup with `make -C infra backup-stack-prod`. It still backs up EMQX,
  because the deployed release is the EMQX one.
- Note the last EMQX main SHA; it is the rollback target.

After it is verified:

- `docker service ls --filter name=off-key_` lists `off-key_mosquitto` and no
  `off-key_emqx-main`.
- `docker service logs off-key_mosquitto` shows `offkey-proxy` connected and no
  `not authorised` lines.
- **Sources** shows readings arriving, and the Grafana collection dashboard shows
  no broker errors.
- The `emqx.` hostname has no route any more. Remove its public hostname from the
  Cloudflare tunnel.

## Rolling back to EMQX

An EMQX release does not know the `mosquitto` service. It would leave it running
on the `emqx-main` alias beside its own broker, so remove it first:

1. Set `AUTO_DEPLOY_ENABLED=false`.
2. On the manager, run `docker service rm off-key_mosquitto` (and
   `docker service rm off-key-demo_mosquitto` for the demo).
3. On the backend node, repeat
   `docker ps -q --filter label=com.docker.swarm.service.name=off-key_mosquitto`
   until it prints nothing.
4. Dispatch **Deploy Production** with the last EMQX SHA. Its `emqx-main` starts
   on its kept volumes with the logins it had when it was stopped. EMQX keeps
   retained snapshots only in memory, so they return with each reading's next
   value, as they do after any EMQX restart.
5. Revert the Mosquitto change on main before enabling automatic deployment
   again, or the next main push moves the stack back to Mosquitto. A revert merged
   while Mosquitto runs needs steps 1 to 3 first, for the same reason.

The Mosquitto volume is left in place by both, so moving forward again starts
from its last snapshots.

Do not change `mqtt_proxy_password` or `mqtt_radar_password` while a rollback is
still possible. EMQX reads its logins from its own volume, not from the vault, so
after a rotation the EMQX release would keep the old passwords and reject the
clients. If they were changed, put the old values back in the vault before
rolling back.

## Rehearsal

The move was rehearsed in a single-node Swarm with the broker service rendered by
the production playbook from both releases: the last EMQX one, then the first
Mosquitto one, with a real CA and broker certificate from
`infra/scripts/generate-mqtt-pki.sh` and a Paho client verifying TLS against
`emqx-main`.

| Step | Result |
| --- | --- |
| EMQX baseline | Login, retained QoS 1 round trip; wrong password and anonymous refused |
| Move (`stack_replaced_services`, then deploy) | 16 s without a broker; same name, certificate and password accepted; no permission warnings |
| Backup (`backup_mosquitto.yml`) | 7 s, manifest with `mosquitto.db` |
| Restore (`restore-stack-state.yml`, `SERVICES=mosquitto`) | A message changed after the backup reads its backed-up value again |
| Password rotation | New password accepted, old refused, retained snapshots kept |
| Rollback to EMQX | 14 s; EMQX accepts the logins it had, not the rotated one |
| Moving forward again | 17 s; Mosquitto restores its last retained snapshots |
| Demo `demo-broker` config | Healthcheck passes, no warnings |

## Cleaning up after the move

Once a rollback to EMQX is no longer wanted:

- Remove the EMQX volumes on the backend node:
  `docker volume rm off-key_emqx_data off-key_emqx_log` (and the `off-key-demo_`
  ones).
- Remove `emqx_dashboard_password` and `emqx_node_cookie` from both vaults.
- Remove old EMQX backups under `infra/stack/state/<env>/emqx/`; restores read only
  `postgres` and `mosquitto` backups now.
- Leave `emqx-main` in `stack_replaced_services`; it does nothing once the service
  is gone and protects a stack restored from an old state.
