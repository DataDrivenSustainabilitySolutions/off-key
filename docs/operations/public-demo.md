---
description: "Run an isolated, public, read-only Aberration installation with public MQTT data and normal administrator access."
---

# Public demo

The public demo uses the same frontend, API, database, recording and monitoring
services as a normal installation. Visitors open **Demo**, immediately left of
**Dashboard** in the landing-page header, without an account. The small **Demo**
menu in the application contains **Admin sign in** and the source attribution.
An administrator signs in normally and can configure sources, recording,
monitors, pipelines and Dojo datasets. Those saved changes become visible to
visitors. Setup never overwrites an existing catalogue.

Public access is an explicit deployment option, disabled by default. The demo
has its own hostname, database, broker, networks and secrets. Never enable it
on an installation containing private data: its catalogue, measurements,
monitoring evidence, pipelines and Dojo datasets become public.

## Public feeds

The initial catalogue contains five providers, six devices and fourteen numeric
readings, recorded every five seconds. A small relay separates individual assets
and gives moving or multiplexed upstream topics stable application topics.
The normal collection and monitoring services process those topics.

| Provider | Selected readings | Reference |
| --- | --- | --- |
| HSL Helsinki tram | Speed, acceleration, schedule offset, door state | [HFP documentation](https://digitransit.fi/en/developers/apis/5-realtime-api/vehicle-positions/high-frequency-positioning/) |
| Hamburg traffic | Occupancy for detectors 13 and 30 | [Hamburg SensorThings](https://tld.iot.hamburg.de/v1.1/) |
| Fintraffic marine | Vessel speed, course, heading | [Marine API](https://www.digitraffic.fi/en/marine-traffic/) |
| Fintraffic rail | Train speed | [Rail API](https://www.digitraffic.fi/en/railway-traffic/) |
| TDengine solar | Inverter power, voltage, temperature, efficiency | [Simulated solar feed](https://tdengine.com/free-public-mqtt-data-feed-real-time-solar-fleet-simulation-now-available/) |

TDengine is explicitly labeled **Simulated**. PONTOS is excluded for now.
Provider attribution and license links are available from **Demo → Data sources**.

The relay rejects retained messages, duplicates, out-of-order readings, non-finite
values and observations older than two minutes or more than ten seconds in the
future. It preserves observation and arrival timestamps in the normalized payload;
the current application's charts use arrival time. Missing upstream data stays
missing. There is no fallback generator. The relay retries failed connections
with bounded backoff and keeps no history queue to replay as fresh data.

Each feed is pinned to a particular asset in `demo_feed_selection`. Train services
and vessels can stop reporting, and a public broker may be unavailable. Check
freshness on the deployment network before launch:

```sh
backend/.venv/bin/python -m off_key_mqtt_proxy.demo.probe --discover --seconds 20 > /tmp/demo-selection.json
backend/.venv/bin/python -m off_key_mqtt_proxy.demo.probe --selection /tmp/demo-selection.json --seconds 20
```

Discovery subscribes briefly to the relevant fleet, selects a fresh asset and
narrows the subscription. It never publishes to a provider. Review the output
before copying it into the inventory. A zero count means no fresh observation was
received during that bounded check, not proof that a source is permanently down.
The implementation check on 2026-11-12 received Hamburg, marine and rail data;
HSL and TDengine did not connect.

When changing an asset after launch, update the relay selection and import an
updated catalogue through normal administration. Generate it with:

```sh
backend/.venv/bin/python -m off_key_mqtt_proxy.demo.relay --selection /tmp/demo-selection.json --catalogue > /tmp/demo-catalogue.json
```

Entity identifiers appear in reading IDs and topics. A different asset therefore
gets a new history; the relay never silently substitutes one under a monitor.
Keep old readings if their recorded history should remain browsable. Changing
deployment selection alone deliberately does not overwrite saved configuration.

## Deploy and activate

1. Use `infra/ansible/inventories/demo/`. Copy `hosts.yml.example` to the ignored
   `hosts.yml`. This can target an existing Swarm; the stack is `off-key-demo`.
   It shares production's non-secret defaults and image manifest, never its vault.
2. Copy `group_vars/all/vault.yml.example` to the ignored `vault.yml`, fill it
   with dedicated credentials and encrypt it with `ansible-vault`. Generate a
   separate 32–72 byte viewer password, for example `openssl rand -hex 32`.
   Generate separate broker certificates using the production PKI procedure.
   Supply the administrator email, mail credentials, registry access and a
   dedicated Cloudflare tunnel token.
3. Configure that tunnel's public hostname `demo.aberration.app` to reach this
   stack's Traefik. The demo ingress exposes only the frontend and API. Review
   backend placement and persistence as for [production](production.md).
4. Deploy from a clean, committed checkout whose SHA has passed the normal image
   and release checks:

   ```sh
   make -C infra deploy-demo REVISION=<tested-full-SHA> BOOTSTRAP=true
   ```

   Omit `BOOTSTRAP=true` on later releases. No new automatic deployment workflow
   is enabled by this feature.
5. Accept the first-administrator invitation at the demo hostname and choose
   your password. Then run `make -C infra initialize-demo`. This creates the
   server-only viewer and seeds an empty catalogue with recording enabled.
   Subsequent releases also run this idempotent initialization after admin setup.
6. Sign in and configure the monitors and datasets to showcase. Verify the same
   pages in a signed-out browser, including fresh measurements and unavailable
   feed states. Public visitors cannot create monitors or upload datasets.
7. Set `demo_base_url: https://demo.aberration.app` in the **production** non-secret
   inventory and release the landing page. An empty value hides the link until
   the deployment is ready. It can also remove the link independently of the
   demo stack. The rendered Demo link remains visible on narrow screens.

The demo viewer is a dedicated `demo-viewer` member. Its sole permission is
`use_dojo`, which the current API requires for Dojo reads as well as writes.
The gateway permits only explicitly listed read requests; it rejects every guest
mutation, including Dojo writes. The viewer token and password never reach the
browser. Every request also checks that the member is active, verified and still
has exactly that role and permission set. Disabling or changing it stops public
access. Administrator tokens continue through normal authorization.

The catalogue revision log and membership endpoints are private. Per-IP guest
limits apply per gateway process; edge rate limits can add a deployment-wide
budget. The initial retention is seven days with a two-GB telemetry ceiling.

## Local rehearsal

Use a separate project and private environment file; do not apply the demo overlay
to an existing development database. Copy `.env.example` to `.env.demo`, set a
unique `DEMO_VIEWER_PASSWORD`, and optionally set `DEMO_FEEDS_JSON`.
The overlay binds the frontend to localhost port 5174 and Mailpit to 8027.
Choose other `DEMO_FRONTEND_PORT` / `DEMO_MAIL_PORT` values if needed.

```sh
docker compose --project-name off-key-demo-local --env-file .env.demo -f docker-compose.yml -f dev/demo/compose.yml up -d --build
docker compose --project-name off-key-demo-local --env-file .env.demo -f docker-compose.yml -f dev/demo/compose.yml exec tactic-middleware /app/bin/python -m off_key_tactic_middleware.bootstrap_admin --send-email
```

Open the invitation in Mailpit, accept it on the local demo, then initialize:

```sh
docker compose --project-name off-key-demo-local --env-file .env.demo -f docker-compose.yml -f dev/demo/compose.yml exec tactic-middleware /app/bin/python -m off_key_tactic_middleware.bootstrap_demo
```

The demo uses project-scoped volumes and networks. RADAR workloads use persistent
lifecycle ownership so this stack does not perform host-wide ephemeral cleanup.
Docker must be running and configured for the application's normal Swarm worker
support; see [local deployment](../development/local-deployment.md).
