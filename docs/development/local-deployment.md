# Local deployment for reworks

Use this workflow to exercise a branch as a complete local application. It builds
the current checkout with the normal Dockerfiles and locked dependencies, serves
the compiled frontend through Nginx, and runs the authenticated gateway, TACTIC,
TimescaleDB, schema bootstrap, MQTT proxy, EMQX, source broker, and Mailpit.

Each checkout gets its own Compose project, application image tags, database,
broker state, and captured email. Default ports differ from the ordinary stack,
so a rework can run alongside an existing preview. Published services bind to
`127.0.0.1`.

## Start

Install Docker with Compose 2.24.4 or newer and Python 3.12 or newer. From the
repository root:

```sh
make local-init
make local-up
make local-bootstrap-admin
```

`local-init` creates `dev/local/.env` with independent random local secrets and a
matching EMQX API bootstrap file. These files are Git-ignored. Repeating init
preserves the existing configuration, project name, and credentials. The project
name initially derives from the checkout path.

Mailpit stores captured messages in its project volume using its
[persistent database option](https://mailpit.axllent.org/docs/configuration/runtime-options/),
so invitations remain available after restarting.

The first build can take several minutes. Startup waits for service health.
`local-up` also builds the RADAR image used by the normal monitoring workflow.
TACTIC runs every RADAR workload as a Swarm service, as in production, so
`local-up` turns a non-Swarm Docker engine into a single-node Swarm manager
(`docker swarm init --advertise-addr 127.0.0.1`) before starting. `docker swarm
leave --force` undoes it once no other Swarm workload needs it.

If Docker Desktop's credential helper hangs while fetching public dependency
images, use `make local-up LOCAL_ARGS=--public-images`. This mode
uses a temporary anonymous Docker configuration against the same verified local
daemon, preserving the installed CLI plugins. Saved Docker credentials stay
unchanged. Use normal mode when your images require registry authentication.

| Service           | Default address                     |
| ----------------- | ----------------------------------- |
| Application       | <http://127.0.0.1:5174>             |
| Monitoring home   | <http://127.0.0.1:5174/>           |
| Entity directory     | <http://127.0.0.1:5174/entities>   |
| Gateway health    | <http://127.0.0.1:8002/health>      |
| TACTIC readiness  | <http://127.0.0.1:8003/ready>       |
| Captured email    | <http://127.0.0.1:8026>             |
| EMQX dashboard    | <http://127.0.0.1:18084>            |
| Local source MQTT | `127.0.0.1:1886`                    |

Open Mailpit, follow the invitation for `admin@example.com`, choose a password,
then sign in to the application. `local-bootstrap-admin` uses the application's
normal invitation workflow. It is safe to repeat; add `LOCAL_ARGS=--resend` to
replace a pending invitation when needed. Database access remains internal on
port 5432; its optional host mapping uses port 5433.

The local frontend accepts `admin` as a shortcut in the **Email** field for the
configured `SUPERUSER_MAIL` account when opened on a loopback address. This uses the normal
authenticated API and the account's saved password; restarting or rebuilding
preserves that account. Ordinary
production builds keep email login and do not enable this local alias.

## Public demo locally

The public demo at demo.aberration.app also runs locally, with the same guest
browsing, read-only viewer account, and Digitraffic catalogue:

```sh
make local-init LOCAL_ARGS=--demo
make local-up
make local-bootstrap-admin
make local-demo
```

`--demo` works on a new or an existing configuration. On an existing one it sets
only `DEMO_MODE`, the viewer account, a random viewer password, and adds the
Digitraffic brokers to `SYSTEM_LIVE_ALLOWED_HOSTS`; everything else is kept.

`local-demo` loads the committed catalogue from
`infra/ansible/inventories/demo/catalogue.json` into an empty installation and
starts sampling every reading each minute. An existing catalogue is kept. It then
creates the viewer account, which needs the administrator to exist: accept the
admin invitation in Mailpit first, then run `make local-demo` again. Both steps
are safe to repeat. Open <http://127.0.0.1:5174> in a private window to browse as
a visitor.

## Exercise MQTT locally

Two sources deliver real MQTT messages through the normal broker and
collector path:

- **Live open data.** `dev/demo/digitraffic_catalogue.py` builds a catalogue
  of Fintraffic road weather, traffic and ferry feeds; see
  [Public demo](../operations/public-demo.md#open-data-sources). Allow
  `tie.digitraffic.fi` and `meri.digitraffic.fi` in
  `SYSTEM_LIVE_ALLOWED_HOSTS`, import the file in **Sources** and choose
  **Connect** or a recording policy.
- **Local synthetic brokers.** The [broker fixture](#mixed-topology-broker-fixture)
  below runs six local brokers with 39 entities.

Numbers and booleans produce charts; text and identifiers show their latest
values.

The generic live preview subscribes directly to each saved connection's exact
topics. Its readings remain in bounded process and browser memory; it does not
write telemetry to the database or change saved collection policies. Disconnecting,
closing the last active view, or changing the saved revision releases subscriptions.
An abandoned connection lease expires after 45 seconds. Saving a document alone
still does not start ingestion.

Administrators can start live subscriptions; members can view an existing live
session. Retained MQTT values are shown as retained readings and do not create
fresh arrival pulses or inflate arrival rates. Connection failures and malformed
payloads appear in the live inspector. Histories begin with observed messages;
exported configuration contains no live values or broker passwords.

The generated broker allowlist contains only the local source broker and the
six optional spatial fixture broker hostnames described below. Testing a
private broker requires explicit local endpoint and credential configuration,
network access, and any required VPN. Credentials stay outside exported system
documents. Production environment files are not used by this launcher.

To allow other generic brokers, edit the private `dev/local/.env` before rebuilding:

```dotenv
SYSTEM_LIVE_ENABLED=true
SYSTEM_LIVE_CONNECT_TIMEOUT_SECONDS=15
SYSTEM_LIVE_ALLOWED_HOSTS='["mqtt.example.com"]'
SYSTEM_LIVE_CREDENTIALS='{"credentials/weather":{"username":"reader","password":"replace-locally"}}'
```

Each broker has a 15-second connection/recovery window by default. Failed
workers stop instead of reconnecting indefinitely; healthy brokers stay live.
When all brokers fail, the browser releases its lease, retains the diagnostics,
and offers **Retry**. Service requests also have a bounded recovery
window. A retry starts a new attempt; it does not change the saved catalogue.

Set a connection's credential reference to `credentials/weather` to use that
private entry. The allowlist matches exact hostnames or IP addresses. TLS uses
certificate verification; MQTT over WebSocket uses the saved path. The client is
the existing [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html)
library. The ordinary stack keeps this preview disabled unless explicitly enabled;
the isolated local workflow allows only its local fixture endpoints by default.

### Simulate an existing catalogue

An exported generic catalogue can drive real, isolated local MQTT brokers:

```sh
python3 dev/local/catalog_fixture.py generate --catalog /path/to/exported-system.json
```

The generated document and Compose overlay stay in ignored `dev/local/state/`
with private file permissions. In private `dev/local/.env`, set
`LOCAL_CATALOG_FIXTURE_ENABLED=true`, `SYSTEM_LIVE_DATA_SOURCE=simulated`, and
`LOCAL_LIVE_TAILNET_ENABLED=false`. Include the catalogue's exact broker hostnames
in `SYSTEM_LIVE_ALLOWED_HOSTS` and remove their entries from
`SYSTEM_LIVE_SOCKS_PROXIES`. Then start the local deployment and choose
**Connect**. This does not import or replace the saved catalogue.

Each distinct hostname gets a separate Mosquitto broker, reachable only inside
this deployment's application network under that catalogue hostname. A bounded
Paho publisher sends numeric, boolean, text and identifier values on the saved
topics. The UI identifies this feed as **Simulated data**, alongside the usual
connection status and controls. No upstream broker is reached,
no broker exposes a host port, and publications are not retained. Each broker
has a 32 MiB memory limit; the publisher has a 128 MiB limit. This fixture supports
plain TCP MQTT on port 1883, up to 128 brokers and 4096 readings. Broker hostnames
must be distinct. Regenerate after changing topic bindings.

### Production vendor access

When Ambibox ingress is enabled, the generic preview can reuse its operator
allowlist, private MQTT credentials and registered `tailscale-ambibox:1055`
endpoint. The production renderer enables live observation with that ingress and
connects the existing tailnet service to the application network. Explicit generic
credential references and per-host proxy settings take precedence. Other brokers
still require their own generic operator allowlist/configuration.

This reads the upstream topics temporarily through the same registered network;
it does not create EMQX collection rules or change collection policies. Production
delivery must be verified after deployment; local simulation verifies the MQTT
client, decoding, leases and UI but cannot establish vendor network health.

### Separate private tailnet device (optional)

The optional `dev/local/compose.live-tailnet.yml` adds a separate local Tailscale
device with persistent state in this deployment's own Docker volume. It uses
userspace networking and exposes a SOCKS5 endpoint only on the application
network. Configure its control server and routes in private `dev/local/.env`:

```dotenv
LOCAL_LIVE_TAILNET_ENABLED=true
LOCAL_LIVE_TAILNET_LOGIN_SERVER=https://vpn.example.com
LOCAL_LIVE_TAILNET_HOSTNAME=aberration-local-development
SYSTEM_LIVE_ALLOWED_HOSTS='["sensor.example.ts.net"]'
SYSTEM_LIVE_SOCKS_PROXIES='{"sensor.example.ts.net":{"host":"live-tailnet","port":1055}}'
```

Start `live-tailnet` with the local Compose files, then run
`python3 dev/local/run.py tailnet-login` and complete the registration it prints.
Once registered, this device restores its own identity across restarts. The
Mac's Tailscale account is independent of this device. Production identity files
must not be mounted or copied into it.

`SYSTEM_LIVE_SOCKS_PROXIES` maps exact broker hostnames to private proxy settings;
unmapped brokers connect directly. The broker allowlist still applies to every
connection. DNS lookup happens at the SOCKS endpoint, and MQTT TLS still verifies
the original broker hostname. Optional proxy username/password fields remain in
private operator configuration; exported catalogues contain no proxy credentials.
The implementation uses Paho's official `proxy` extra.

MQTT credentials remain separate from tailnet registration: set a broker's
`credential_ref` and the matching `SYSTEM_LIVE_CREDENTIALS` entry if required.

## Mixed topology broker fixture

```sh
python3 dev/local/run.py up --broker-fixture
```

This opt-in profile starts **six independent Eclipse Mosquitto brokers** and one
publisher using the existing Paho dependency. The brokers expose no host ports.
They belong only to this checkout's isolated Compose project. The ordinary stack
and other local deployments are unchanged.

In **Sources**, explicitly import `dev/local/broker-system.json`, then
choose **Connect**. Import replaces the current saved system; export any
configuration you want to keep first. The catalog contains three shared brokers
(12 rooms, 12 machines, and 12 growing beds) and three dedicated single-entity
brokers (power meter, weather station, water pump): 39 entities, 183 distinct MQTT
topics, and 300 streams. **Station 01** has 48 additional topics across Thermal,
Mechanical, Electrical, and Diagnostics categories, on its shared production
broker. **Main power meter** has 96 additional topics covering eight circuits,
three phases each, and voltage/current/power/frequency, on its dedicated broker.
These dense entities have 49/97 topics and 52/100 streams respectively, including
their original four-field telemetry topic.
There are no predefined personal groups; broker/entity/topic references describe
the source structure, and users can add their own organization in the UI.

Each entity sends a real, non-retained JSON MQTT message containing a numeric
measurement, boolean activity, text mode, and sample identifier. Its four stream
pointers extract those fields from that one delivery. Cadences vary from 0.8 to
8 seconds. The 144 additional channels each publish a separate numeric JSON
message on their own exact topic every 4–24 seconds. These source categories and
topic paths are catalog metadata, independent of personal groups. Values are
deterministic synthetic waves and state transitions. Combined traffic averages
about 40 MQTT messages per second; a fair scheduler sends at most six messages
per 100 ms tick, preventing a large burst after a stall.
Disconnected publishers discard missed intervals rather than replaying backlog.
Per-broker queues are bounded, and all collection policies remain off. Live
readings use the existing bounded memory preview without database retention.

New `local-init` configurations include the fixture allowlist. Existing private
`dev/local/.env` files are preserved: append these exact hosts to the existing
`SYSTEM_LIVE_ALLOWED_HOSTS` array before starting this profile:

```text
fixture-broker-campus
fixture-broker-production
fixture-broker-greenhouse
fixture-broker-meter
fixture-broker-weather
fixture-broker-pump
```

Regenerate the catalog after changing fixture definitions using
`python3 dev/local/broker_fixture.py --write-catalog`; check that the tracked
catalog matches using `--check-catalog`. `make local-stop` also stops the optional
profile without deleting application state. Omitting `--broker-fixture` on later
starts does not stop a previously running profile; use `local-stop` when done.

## Iterate and restart

```sh
make local-status
make local-logs LOCAL_ARGS="api-gateway tactic-middleware"
make local-up
make local-stop
```

Re-run `local-up` after source changes to rebuild and deploy the checkout. The
frontend is a compiled bundle, so this mode exercises built assets and same-origin
`/api` routing. Use host-side Vite for the faster editing loop.

`local-stop` stops Compose services and preserves the database and broker
volumes. Re-running `local-up` uses the saved configuration. Stop any dynamic
monitoring services through the application before stopping the stack; RADAR
workloads use the persistent lifecycle and are managed separately from Compose.

For another set of ports or an explicit project name, set them on the first init:

```sh
python3 dev/local/run.py init --project offkey-my-rework --frontend-port 5180 --api-port 8012
```

The remaining port settings live in the private `dev/local/.env`. Keep the
frontend origin and CORS configuration consistent if editing that file directly.
The launcher ignores ambient shell overrides for Compose interpolation variables,
so the local configuration determines this deployment.

## Compiled application

Development and production builds use the same monitoring home and catalogue
sidebar. No experiment flag or separate demo route is required.

The tracked launcher and override are in `dev/local/`. They reuse the root
Compose services and contain no machine-specific absolute paths or private
catalogs.

The local Docker management proxy is pinned to the official
[v0.4.2 release](https://github.com/Tecnativa/docker-socket-proxy/releases/tag/v0.4.2)
from the vendor's recommended GHCR registry. Set `LOCAL_SOCKET_PROXY_IMAGE` in
the private local environment to validate a newer release before adopting it.

## Upgrade this iteration

The generic catalogue is the only active format. The packaged migration action
converts existing database configuration once without deleting sensor measurements
or latest values; recording and retention keep their existing behaviour. Preserve the
local database volume and private `.env`. Stop application writers before applying
migrations, then rebuild/recreate the API, TACTIC, collector and DB sync; also build
the RADAR runtime image before starting monitors. Never use a database reset to
upgrade a saved installation.

The ignored private `infra/stack/state/prod/ambibox-development-system.json` is the
converted generic Ambibox example for local import. It contains configuration
only; MQTT passwords and private network access remain operator settings. Its
original catalogue file remains a private archive.
