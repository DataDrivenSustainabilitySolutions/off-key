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

## Cloudflare entry check

The hosted demo uses a Cloudflare WAF custom rule named **Demo entry
verification**, with expression `(http.host eq "demo.aberration.app")` and action
**Managed Challenge**. This applies to the entire demo hostname, including its
API. After a visitor passes the check, Cloudflare's clearance cookie permits
subsequent requests. If public-access discovery or session restoration encounters
the challenge, **Verify browser** reloads the current page so Cloudflare can
complete its check. This preserves the destination and saved login; ordinary API
permission failures do not trigger browser verification. Automated clients
without clearance are challenged.
The rule does not match production hostnames and needs no application widget key.

The demo inventory lists its URL in `release_public_challenge_urls`. Deployment
still requires database, application and worker readiness, then the external
probe must receive HTTP 403 with `cf-mitigated: challenge`. A plain access-denied
response or an unprotected success response fails that check. Configure the rule
before deploying this inventory; installations without an entry challenge should
leave that list empty. Production's ordinary public-route checks are unchanged.

See [Cloudflare clearance](https://developers.cloudflare.com/cloudflare-challenges/concepts/clearance/)
and [challenge-response detection](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/).

## Public feeds

The initial catalogue contains three sources, three devices and twelve numeric
readings, sampled at five-second intervals when new messages arrive. The sources
report at different cadences; a quiet or unavailable upstream never produces
invented readings. A small relay separates individual assets and gives upstream
topics stable application topics.
The normal collection and monitoring services process those topics.

| Provider | Selected readings | Reference |
| --- | --- | --- |
| Fintraffic road weather | Air and road surface temperature, mean wind, humidity at one station | [Road traffic API](https://www.digitraffic.fi/en/road-traffic/) |
| Fintraffic traffic counts | Vehicles per hour and average speed in both directions at one station | [Road traffic API](https://www.digitraffic.fi/en/road-traffic/) |
| Mosquitto public broker | Connected clients, received/sent messages per minute, received bytes per minute | [Public test broker](https://test.mosquitto.org/) |

Provider attribution and license links are available from **Demo → Data sources**.

Fintraffic weather updates can be several minutes apart; traffic counts are
five-minute sliding values. Mosquitto reports
real operational metrics, typically about every ten seconds. It is a public test
service, so interruptions are possible. Single trams, trains and vessels
were dropped from the initial selection because they only report while that one
vehicle is in service.

The relay rejects retained messages, duplicates, out-of-order readings, non-finite
values and observations older than two minutes (ten for the Fintraffic road
stations, which publish a measurement about a minute after taking it) or more
than ten seconds in the future. It preserves observation and arrival timestamps
where the provider supplies them. Mosquitto's numeric `$SYS` messages have no source
timestamp: their observation time remains null and fresh delivery is recorded
at arrival. Retained snapshots are discarded. The current application's charts
use arrival time. Missing upstream data stays
missing. There is no fallback generator. The relay retries failed connections
with bounded backoff and keeps no history queue to replay as fresh data.

Each feed is pinned to a particular asset in `demo_feed_selection`. A station can
be out of service, and a public broker may be unavailable. Check
freshness on the deployment network before launch:

```sh
backend/.venv/bin/python -m off_key_mqtt_proxy.demo.probe --discover --seconds 20 > /tmp/demo-selection.json
backend/.venv/bin/python -m off_key_mqtt_proxy.demo.probe --selection /tmp/demo-selection.json --seconds 20
```

Discovery subscribes briefly to the documented `weather-v2/#` and `tms-v2/#`
network topics, selects a fresh asset and narrows the subscription. For the road
networks it picks the first station heard,
so prefer a known station with every sensor and check it with `--selection`. It never publishes to a provider. Review the output
before copying it into the inventory. A zero count means no fresh observation was
received during that bounded check, not proof that a source is permanently down.
On 2026-11-13, weather station 1003 supplied all four selected measurements,
traffic station 23438 supplied fresh readings, and all four Mosquitto
metrics arrived over verified TLS from the demo worker. The invalid weather
station 4057 and unreachable TDengine endpoint were replaced. These checks do not
guarantee future provider availability; verify freshness before each launch.

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
   The whole demo runs on one worker. Choose the one with the most free CPU and
   memory, list it as both backend and frontend node, and label it once from the
   manager with `docker node update --label-add offkey-demo=true <worker>`.
   Production's labels and nodes are left alone.
2. Copy `group_vars/all/vault.yml.example` to the ignored `vault.yml`, fill it
   with dedicated credentials and encrypt it with `ansible-vault`. Generate a
   separate 32–72 byte viewer password, for example `openssl rand -hex 32`.
   Generate separate broker certificates using the production PKI procedure.
   Supply the administrator email, mail credentials, registry access and a
   dedicated Cloudflare tunnel token.
3. Configure that tunnel's public hostname `demo.aberration.app` to reach this
   stack's Traefik: service type HTTP, URL `traefik:80`. The demo's networks are
   its own, so that name reaches the demo's Traefik. The demo ingress exposes only
   the frontend and API. Persistence works as in [production](production.md);
   with a single node, node-local volumes stay with the stack.
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

The catalogue revision log and membership endpoints are private. Proposals are
public, because they show what agents designed and why: a guest sees an agent
by its name and a member only as "A member", never by email. Per-IP guest
limits apply per gateway process; edge rate limits can add a deployment-wide
budget. The initial retention is fourteen days with a two-GB telemetry ceiling: long
enough for a week of calibration and for a test on the last days of history.

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
