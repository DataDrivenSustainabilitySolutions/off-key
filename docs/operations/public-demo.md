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

## What runs where

The demo is a second, small stack (`off-key-demo`) on the production Swarm,
with its own database, broker, TACTIC, API and frontend, and at most two
monitors. **Deploy Production** deploys it right after production, from the
same commit and images. The `inventories/demo` inventory leaves out the broker
route, Traefik, the Cloudflare connector, the oauth2-gated EMQX and
Traefik dashboards and the landing page. Collection may only reach the
Digitraffic brokers. A test keeps every other setting equal to production.

Production's Traefik serves `demo.aberration.app` through the existing
tunnel. It joins the `aberration-demo` network, which only the demo's
frontend and API share, and addresses every service by its stack-qualified
name (`off-key_frontend`, `off-key-demo_frontend`), so the two stacks never
answer for each other. Production deployments, backups and restores only
touch their own monitor workers, and each TACTIC only manages its own.

The demo's TACTIC has Docker access on the cluster, like production's. It is
not reachable from the internet; guests only reach the allowlisted reads.

## Set up the demo (one time)

1. **Cloudflare.** The tunnel's public hostname `demo.aberration.app` points
   at `http://traefik:80`, like the dashboard's.
2. **Vault.** Copy `infra/ansible/inventories/demo/group_vars/all/vault.yml.example`
   to `vault.yml` and fill in new secrets. Only the Resend key may repeat
   production's; create the EMQX certificates with
   `infra/scripts/generate-emqx-pki.sh`. Set a random
   `demo_viewer_password`, then encrypt the file with the production vault
   password: `ansible-vault encrypt vault.yml`.
3. **GitHub.** In the **production** environment, add the secret
   `OFFKEY_DEMO_VAULT` with the encrypted file and the variable
   `DEMO_ENABLED` = `true`. The demo uses production's inventory, SSH key and
   tailnet access.
4. **Deploy.** Under **Actions → Deploy Production → Run workflow**, paste
   the commit SHA production runs (a release that includes this demo setup)
   and check **demo_only**. The run creates
   the demo stack and emails the administrator invitation to the vault's
   `superuser_mail`.
5. **Open it to visitors.** Accept the invitation, then run the workflow
   again with **demo_only**. That run creates the viewer member, and the log
   says *Demo viewer created*. Signed-out visitors of `demo.aberration.app`
   now browse read-only.
6. **Monitors.** The first deployment loads the committed Digitraffic
   catalogue (below) and records every reading once a minute. Signed in as
   administrator, start the monitors you want to show.
7. **Landing page.** Set `demo_base_url: "https://demo.aberration.app"` in
   the production inventory so the landing page shows **Demo** next to
   **Dashboard**.

From then on every production release also deploys the demo when it has
runtime changes. `make deploy-demo REVISION=<sha>` runs the demo-only
deployment from a terminal. Set `DEMO_ENABLED` to `false` to stop deploying
it; `docker stack rm off-key-demo` on the manager removes it.

Changing the viewer's password in the vault refreshes it on the next deploy
and revokes its session; the gateway signs in again on the next guest
request. Disabling the viewer under **Account → Members** closes the demo to
visitors (they see "unavailable"), and deployments leave it disabled.

## Open data sources

`dev/demo/digitraffic_catalogue.py` builds a catalogue from
[Fintraffic Digitraffic](https://www.digitraffic.fi/en/) open data
(CC BY 4.0, anonymous MQTT over secure WebSockets):

| Feed | Topics | Readings | Rate |
| --- | --- | --- | --- |
| Road weather station nearest the city | `weather-v2/<station>/<sensor>` | Air and road temperature, humidity, wind | About once a minute |
| Traffic measurement station nearest the city | `tms-v2/<station>/<sensor>` | 5-minute traffic flow and average speed per direction | About once a minute |
| One passenger ferry (AIS) | `vessels-v2/<mmsi>/location` | Speed and course over ground | While under way |

The demo's catalogue is committed as
`infra/ansible/inventories/demo/catalogue.json`. A deployment loads it only
into a demo without a catalogue, so the administrator's later edits stay.
Station and vessel IDs change over time, so the script looks them up through
the Digitraffic REST API. To refresh the committed file, run it from a
machine with internet access:

```bash
uv run --project backend python dev/demo/digitraffic_catalogue.py \
  --city helsinki --verify --output infra/ansible/inventories/demo/catalogue.json
```

`--verify` listens for 150 seconds and leaves out readings that sent
nothing; pass a longer time, such as `--verify 300`, for quiet sensors. Use
`--vessel-topic locations` if the ferry stays silent. A running demo keeps
its catalogue; import the refreshed file under **Sources → catalogue
settings**, then choose a recording policy and **Apply**: imported policies
never start collection by themselves. Name Fintraffic as the source wherever
the demo is presented; the broker labels already do.

## Run the demo locally

The same demo runs on a local deployment with `make local-init
LOCAL_ARGS=--demo` and `make local-demo`; see
[Local deployment](../development/local-deployment.md#public-demo-locally).
