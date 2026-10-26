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

The demo runs on its own small server, deployed by the **Deploy Demo**
GitHub workflow with the same Ansible playbooks and release images as
production. The `inventories/demo` inventory switches off what a public demo
must not have: Ambibox vendor ingress, the oauth2-gated EMQX and Traefik
dashboards, and the landing page. Collection may only reach the Digitraffic
brokers. A test keeps every other setting equal to production.

The demo has its own Cloudflare Tunnel. It must not share the production
tunnel: Cloudflare spreads a tunnel's traffic over all of its connectors, so
a demo connector on the production tunnel would receive production requests.

## Set up the demo (one time)

Everything except the server, the tunnel and the GitHub settings runs from
GitHub.

1. **Server.** Create an Ubuntu 24.04 server with 4 vCPUs and 8 GB of memory,
   with a `deploy` user that has passwordless sudo and the deployment SSH
   public key from [GitHub setup](github-setup.md) in `authorized_keys`.
2. **Cloudflare Tunnel.** In Cloudflare **Zero Trust → Networks → Tunnels**,
   choose **Create a tunnel → Cloudflared**, name it `aberration-demo` and
   copy the `eyJ…` token from the install command. Under **Public Hostname**,
   add subdomain `demo`, domain `aberration.app`, type **HTTP**, URL
   `traefik:80`. If `demo.aberration.app` is already a public hostname of the
   production tunnel, delete it there first.
3. **Vault.** Copy `infra/ansible/inventories/demo/group_vars/all/vault.yml.example`
   to `vault.yml`, fill in new secrets (only the management-tailnet key,
   Resend key and registry placeholders may repeat production's), the
   `aberration-demo` tunnel token, and a random `demo_viewer_password`. Then run
   `ansible-vault encrypt` on it.
4. **Inventory.** Copy `inventories/demo/hosts.yml.example` to a private
   `hosts.yml`. For the first run use the server's public address; after
   provisioning you can switch to its management-tailnet address.
5. **GitHub environment.** In **Settings → Environments**, create `demo`,
   limited to `main`. Add the variable `DEMO_AUTO_DEPLOY_ENABLED` = `false`
   and these secrets:

   | Secret | What to paste |
   | --- | --- |
   | `OFFKEY_DEMO_VAULT` | The encrypted demo `vault.yml`. |
   | `OFFKEY_VAULT_PASSWORD` | Its vault password. |
   | `OFFKEY_DEMO_INVENTORY` | The demo `hosts.yml`. |
   | `OFFKEY_DEPLOY_SSH_KEY` | The deployment private key. |
   | `OFFKEY_DEPLOY_KNOWN_HOSTS` | The demo server's verified host key, for every address in the inventory. |
   | `TS_OAUTH_CLIENT_ID`, `TS_AUDIENCE` | A Tailscale federated identity like production's, trusting the `demo` environment and `deploy-demo.yml` on `main`. |

   Allow `tag:offkey-ci` to reach the demo server on TCP 22 in the
   management tailnet policy.
6. **Provision.** Under **Actions → Deploy Demo → Run workflow**, paste the
   commit SHA production runs and check **provision**. The workflow installs
   Docker, Tailscale and Swarm, deploys the stack and emails the administrator
   invitation to `superuser_mail`.
7. **Open it to visitors.** Accept the invitation, then run **Deploy Demo**
   again with the same SHA and **provision** unchecked. That run creates the
   viewer member, and the log says *Demo viewer created*. Signed-out visitors
   of `demo.aberration.app` now browse read-only.
8. **Sources and monitors.** Signed in as administrator, import the
   Digitraffic catalogue (below), apply a recording policy and start the
   monitors you want to show.
9. **Follow production.** Set `DEMO_AUTO_DEPLOY_ENABLED` to `true`. Each
   successful **Deploy Production** run with runtime changes then deploys the
   same commit to the demo. Set `demo_base_url: "https://demo.aberration.app"`
   in the production inventory so the landing page shows **Demo** next to
   **Dashboard**.

To change a demo setting later, update the `OFFKEY_DEMO_VAULT` or
`OFFKEY_DEMO_INVENTORY` secret, or `inventories/demo` in a pull request, and
run **Deploy Demo**. `make deploy-demo REVISION=<sha>` dispatches it from a
terminal.

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
