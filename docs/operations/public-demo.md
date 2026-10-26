# Public demo

A public demo is a separate Aberration installation, such as
`demo.aberration.app`, that anyone can browse without signing in. Visitors
see real sources, recorded readings, monitoring services and anomalies, and
can change nothing. Administrators sign in as usual and configure it like any
other installation.

## When to use this page

Use this page to set up or operate the read-only demo, or to check what its
signed-out visitors can reach.

## How read-only is enforced

The gateway enforces it; the browser only hides controls.

- With `DEMO_MODE=true`, a request without an `Authorization` header is a
  guest. Guests reach only the read routes listed in
  `off_key_api_gateway.api.demo.GUEST_ROUTES`. Every other call, including a
  route added later, answers 403 until it is listed. A test fails when a
  listed route does not exist or an unlisted one answers a guest.
- The gateway signs guest requests in as one ordinary member, the *viewer*,
  so TACTIC applies the member role to every call as well. A viewer with the
  administrator role is refused and the demo answers 503.
- Guests never reach member administration, favourite changes, live
  previews, sign-in sessions or the system revision log, which names the
  members who saved.
- Each visitor address may send `DEMO_GUEST_REQUESTS_PER_MINUTE` guest
  requests (240 by default). Pipeline read limits apply per visitor, not to
  the shared viewer.
- Requests that carry a token are unchanged, so administrators work as on
  any installation. Public registration stays off.

Use a separate installation with its own database, vault and broker
allowlist. One installation serves one organization, so a demo inside a
production installation would show that organization's data.

## Set up an installation

1. Deploy the installation with its own hostname, database and secrets, as
   in [Production releases](production.md). Its vault must not contain
   private broker credentials, SOCKS routes or tailnet access.
2. Invite the first administrator, then invite the viewer as a **member**
   from **Account → Members** with an address you control, and choose its
   password from the invitation. Store the password only in the vault.
3. Set `DEMO_MODE=true`, `DEMO_VIEWER_EMAIL` and `DEMO_VIEWER_PASSWORD` for
   the API gateway and restart it. `GET /api/v1/demo` now answers
   `{"enabled": true}`.
4. Allow only the demo brokers, for example
   `SYSTEM_LIVE_ALLOWED_HOSTS=["tie.digitraffic.fi","meri.digitraffic.fi"]`.
   Keep `TACTIC_RADAR_MAX_ACTIVE_MONITORS` and `TELEMETRY_RETENTION_DAYS`
   small, for example `4` and `7`.
5. Set `demo_base_url` in the production inventory, for example
   `https://demo.aberration.app`. The landing page then shows **Demo** next
   to **Dashboard** and a link under the headline.

Changing the viewer's password or access revokes its session; the gateway
signs in again on the next guest request.

## Open data sources

`dev/demo/digitraffic_catalogue.py` builds a catalogue from
[Fintraffic Digitraffic](https://www.digitraffic.fi/en/) open data
(CC BY 4.0, anonymous MQTT over secure WebSockets):

| Feed | Topics | Readings | Rate |
| --- | --- | --- | --- |
| Road weather station nearest the city | `weather-v2/<station>/<sensor>` | Air and road temperature, humidity, wind | About once a minute |
| Traffic measurement station nearest the city | `tms-v2/<station>/<sensor>` | 5-minute traffic flow and average speed per direction | About once a minute |
| One passenger ferry (AIS) | `vessels-v2/<mmsi>/location` | Speed and course over ground | While under way |

Station and vessel IDs change over time, so the script looks them up through
the Digitraffic REST API. Run it from a machine with internet access:

```bash
uv run --project backend python dev/demo/digitraffic_catalogue.py \
  --city helsinki --verify --output digitraffic-system.json
```

`--verify` listens for 150 seconds and leaves out readings that sent
nothing; pass a longer time, such as `--verify 300`, for quiet sensors. Use
`--vessel-topic locations` if the ferry stays silent. Import the file under
**Sources → catalogue settings**, then choose a recording policy and
**Apply**: imported policies never start collection by themselves. A sample
interval of 60 seconds matches the source rate. Name Fintraffic as the
source wherever the demo is presented; the broker labels already do.
