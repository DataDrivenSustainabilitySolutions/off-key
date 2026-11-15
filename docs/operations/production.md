# Production releases

Production runs Docker Swarm from `infra/`. Local development remains Docker Compose;
there is no staging environment. Application, migration and infrastructure files are
released from one tested main commit. See [GitHub setup](github-setup.md) before cutover.

## Release sequence

1. The latest attempt of the CI run for the main push of that SHA must succeed
   ([Contributing and CI](../development/contributing-ci.md#current-automated-checks)).
   CI holds every release gate, so this one run covers them all.
2. One GitHub production job connects through an ephemeral management-tailnet runner
   and verified SSH. Superseded automatic candidates stop before deployment.
3. Runtime files are compared against the manager's last verified release. Root-level Markdown
   and test-only changes do not deploy; intervening undeployed runtime changes remain visible.
4. Deployment uses the exact immutable image digests saved by that SHA's successful
   CI release evidence: a full rehearsal, or verified reuse of tested images after
   focused static-content checks. OCI revision labels must match each image's proven
   source revision; a missing or expired artifact blocks deployment, so a root-Markdown-only `main` run, which
   rehearses nothing, is never selected. The control checkout must be clean and match
   that same commit.
5. A durable database operation fences monitor start/stop/delete and catalog writes.
   Normal requests receive HTTP 503 during release maintenance.
6. Pending schema migrations require every database writer to stop: TACTIC,
   db-sync, the MQTT proxy, the Dojo workers and the RADAR workers. A Dojo run
   in progress goes back to the queue and starts again afterwards; one whose
   worker cannot stop in time is marked failed. Ingress, the landing page, the
   frontend and the gateway keep running, so the public site stays up. A validated
   custom-format backup stays private on the database node. SQL and checksum ledger
   changes commit together under a PostgreSQL advisory lock.
7. Active monitor configurations are saved, their actual old tasks must stop, and
   new UUIDs restart the same monitors with fresh calibration. Pending user stop
   intent is honored. Historical telemetry/evidence remains; old checkpoints are
   never loaded by a new UUID.
8. The stack, image/replica plan, schema/API readiness, collector/catalog routing,
   restarted worker heartbeats and public HTTP routes must pass verification.
   Waiting for charger data is valid. A selected broker that is unreachable or refuses
   the connection is reported, not failed: the release cannot fix a broker. Missing
   operator access for a selected broker still fails. Only then is maintenance
   completed and `release.json` replaced. An interrupted release cannot be replaced
   by another SHA.
9. Application setup follows the completed release: the first administrator
   invitation. It writes like any client, so a failure fails the run without
   holding the release open; a retry or the next deployment repeats it.

Frontend/docs updates can retain running application writers and monitor UUIDs.
This path requires an existing private `verified-deployment.json` baseline, only
static source changes, identical non-image configuration and non-static images,
identical live Docker service specs, and no pending filesystem or database recovery
operation. It takes the same durable release reservation, briefly fencing catalogue
and monitor configuration writes while ingestion and existing workers continue.
It rechecks the baseline immediately before updating only the changed static images.
Worker image/secret checks, schema and collection readiness, full
Swarm convergence, existing worker heartbeats and public routes still gate success.
Any uncertainty selects the complete sequence above. The baseline is recorded only
after successful verification; losing this optional file selects a full cutover.
CI updates disposable frontend/docs images and back while checking that backend tasks,
an active monitor and real ingestion survive unchanged.

Writer scaling during a full cutover submits all selected service counts together
and waits for Docker convergence. Before any backup or replacement, the additional
actual-task fence still requires every retiring writer to have stopped. Failed
writer resumption preserves the original recovery plan and replica counts.

Dispatch a tested release manually with `make deploy-prod REVISION=<full SHA>`.
Use `BOOTSTRAP=true` only for the first integrated cutover. The automatic switch
starts disabled. Production secrets/configuration changes require a manual dispatch.

The workflow captures Ansible output in private temporary files and deletes it with
its configuration at job exit. A failed step prints only the names of the Ansible
tasks that failed (`infra/scripts/failed_tasks.py`), never their output, and for a
failed readiness probe the fixed name of the check that failed, such as
`ingress heartbeat`. Each release also prints its task count, elapsed time and
slowest task names with their durations (`infra/scripts/task_timings.py`), so slow
steps are visible without the log. SSH connections to the nodes are reused across
tasks. The workflow runs these reporting tools from its own checkout, so a retry
or rollback of an older SHA reports the same way.

Each release's full Ansible log is kept on its manager under
`<stack_dir>/release-logs/`, readable by root only, newest 20 releases. A failed
or refused release opens the issue **Production release needs attention** with
those public lines and the retry step, and mentions whoever triggered it. Later failures comment on the same issue,
and the next completed release of that target closes it. Database backups, the broker
route identity, recovery records and private inventories are not published as Actions
artifacts. Investigate live failures through trusted SSH and the server-side
records, not public log uploads.

## Schema baseline and database reset

The schema has one baseline. An empty database receives the current schema from
the ORM bootstrap and records `000_baseline.sql` in its migration ledger; later
migrations follow it in order. A database created before the baseline carries the
retired migrations 001–035 or none at all. It cannot be upgraded: the migration
preflight refuses it before any writer stops, so production keeps running the
release it has and the task **Refuse a database from before the schema baseline**
fails.

Start such a stack from an empty database with an explicit reset. It names the
stack it erases:

```sh
make deploy-prod REVISION=<full SHA> RESET_DATABASE=off-key
```

or, in the **Deploy Production** workflow, type `off-key` in *reset_database*.
The release stops every writer, saves a validated custom-format backup to
`<stack_dir>/.backup/resets/<UTC time>/database.dump` with its checksum on the
database node, drops and recreates the database with TimescaleDB, and then
deploys as on a new cluster. Every account, monitor, design, proposal, dataset,
alarm and reading is gone; the administrator invitation is emailed again at the
end of the release. Each reset keeps its own backup, so a retry never replaces
the backup of the data with one of the empty database. Restore it with the
[recovery](recovery.md) procedure if it is needed again; the restored data only
runs on a release from before the baseline.

The [demo](public-demo.md#reset-the-demo-database) resets the same way from its
own inventory.

## Checks before production

The `deployment-smoke` CI lanes run the existing browser and adaptive-monitor journeys against a
disposable Swarm using the production frontend, TLS/authenticated MQTT and deployment
tasks. PRs build production images; on main both smoke lanes start only after the
same run's `publish` job pushed the images, and they test those digests before making
them eligible for deployment. The restore test creates its own state on the fresh
Swarm: synthetic accounts with a custom role, a remembered session and a pending
invitation, favourites, manual alarms a week apart, saved catalog definitions,
telemetry and a running monitor must survive actual database backup/restore and
repeated deployment, with exactly one restarted monitor and resumed collection.

The database integration job uses the pinned production TimescaleDB image and checks
schema bootstrap, hypertables, constraints, retention jobs and real retention deletion
in isolated databases. Existing fast unit/configuration tests remain in place.

External email, source brokers and VPN transport use local fixtures. Live verification
still checks the actual service images, schema, collector, restarted monitors and
public routes. The rehearsal artifact contains image references only and is retained
for 90 days; synthetic failure diagnostics do not contain production configuration.

## Provisioning and existing state

For controlled provisioning, use `make -C infra provision-prod REVISION=<full SHA>
BOOTSTRAP=true` with the ignored inventory and encrypted vault. Existing SSH users,
node names, ports, management Tailscale enrollment and node labels remain authoritative.
The inventory must contain exactly one Swarm manager; every operator playbook checks
this on the controller before contacting hosts.
The broker route's node identity must exist on the manager's NFS export or be
restored from a private seed before deployment. CI never registers a replacement
route device. Its MQTT login belongs in the vault as `broker_route_mqtt_username`
and `broker_route_mqtt_password`; deployment stops without it unless
`broker_route_anonymous` is set.
NFS permits the discovered backend management-tailnet /32 addresses only.

Provisioning installs the Docker Engine release pinned as `docker_engine_version` in
`infra/ansible/roles/docker_install/defaults/main.yml`, and CI's Swarm jobs replace
the runner's engine with the same release. Docker 28's Swarm manager crashes when a
removed service's tasks are reaped at the same moment, which TACTIC's worker
removals trigger; the swarmkit in current Docker 29 releases fixes it. Automatic
deployments never change the engine, and provisioning restarts Docker on each node,
so run it in a maintenance window after raising the pin.

Persistence changes keep the existing explicit confirmation/backup/restore guard.
Automatic CD never supplies confirmation. Do not combine the initial integration
cutover with a persistence flip. Recover state first using [Recovery](recovery.md).

## Image retention

Each main push publishes seven application images and their attestations to GHCR,
and each release pulls seven new images onto the nodes. Neither place keeps them all.

- **Nodes:** after a release is verified and recorded, `deploy.yml` removes the
  application images on every node that neither the release nor any Swarm service
  names, so TACTIC's runtime RADAR images stay. It never runs a
  broad `docker image prune`: digest-pulled images look dangling, and runtime RADAR
  workers cannot pull a removed image again without registry credentials. Images that
  Swarm's task history still holds stay until that history rotates. A cleanup error is
  reported in the log and never fails a verified release.
- **GHCR:** the weekly `GHCR Retention` workflow keeps the newest 20 releases of each
  image, `latest`, every digest pinned in `release.yml` and the attestations of the
  images it keeps. It only lists what it would delete until the repository variable
  `GHCR_RETENTION_ENABLED` is `true`; a manual run with `delete` deletes once. Retries
  and rollbacks to an older SHA need its images, so keep enough releases to cover the
  oldest SHA you might roll back to.

## Credentials, ingress and certificates

The encrypted production vault remains the configuration source. The production
workflow temporarily unlocks it, uses a short-lived GHCR token and deletes runner
files; backend and manager registry sessions log out even on failure. A local
operator may still use an independently stored recovery registry credential.

Cloudflare's existing tunnel routes HTTPS hostnames to Traefik. Configure public
routes/DNS in Cloudflare, matching the committed production hostname settings.
The tunnel token is a versioned Swarm secret. oauth2-proxy limits the broker and
Traefik dashboards to the configured GitHub organization/user allowlist. It checks
organization membership only at sign-in, so its `SameSite=Lax` session lasts 12
hours (`oauth2_cookie_expire`) and is re-validated against GitHub hourly
(`oauth2_cookie_refresh`). Someone removed from the organization keeps access for
at most that long; rotate `oauth2_cookie_secret` to end every session at once.

EMQX clients use TLS and separate least-privilege users, with credentials mounted as
versioned Swarm secrets. Generate/validate certificate material using
`infra/scripts/generate-emqx-pki.sh` and `validate-emqx-pki.py`; keep private keys in
the encrypted vault. When changing a client password, rotate the existing EMQX user
first; the playbook rejects changing only bootstrap/client values on a running broker.
The broker's Erlang distribution (`emqx ctl`, clustering) is authenticated with
`emqx_node_cookie` from the vault: at least 32 characters from letters, digits, `_`
and `-`, for example from `openssl rand -hex 32`. Changing it restarts the broker;
stored broker data is unaffected.

A release that needs a vault variable the production vault lacks stops before it
changes anything. Tests and the rehearsal cannot see this, because they render with
synthetic secrets; the real vault is read only by a production release. The failed
task names the variable, for example `Require a dedicated EMQX node cookie (vault
emqx_node_cookie)`, and `vault.yml.example` describes its value. Add it with
`ansible-vault edit`, replace the `OFFKEY_PROD_VAULT` environment secret with the
whole encrypted file, then dispatch the same tested SHA again.

Production email uses the configured Resend SMTP account with TLS and verified
sender DNS. Save its key as `email_password` in the encrypted vault. First-admin
invitation runs after readiness; `make -C infra invite-admin-prod` can resend it.
Local Compose uses Mailpit. No production Mailpit service remains.

## Documentation hosting

`https://docs.aberration.app` serves the public Zensical documentation from the
`docs` service on the existing production Swarm. CI builds `off-key-docs` with
`dev/docs/Dockerfile`, runs a strict build and checks the resulting HTTP server,
then publishes and attests it. For documentation-only changes, CI reuses verified
application images and skips unrelated application tests and Swarm rehearsals. Deployment
uses the tested image digest. Documentation-only changes trigger deployment too.
The image includes `llms.txt`, `llms-full.txt` and per-page Markdown exports.

The committed release manifest initially names `off-key-docs:latest` because the
new package has not been published yet. CI replaces that seed with a verified
commit-specific digest in its `production-release` artifact. Production rejects
unpinned images; do not deploy the seed manifest directly or invent a digest.
Offline rendering tests substitute a synthetic digest only in their fixtures.

Before deploying the first release with this service, configure Cloudflare:

1. Open **Networking → Tunnels**, select the existing production tunnel, and add
   a **Published application** route (called **Public Hostname** in some views).
2. Set the hostname to **docs.aberration.app**, leaving the path unrestricted.
3. Set the service to **HTTP**, URL **traefik:80** (`http://traefik:80`). Keep
   **HTTP Host Header** unset so the original `docs.aberration.app` host reaches
   Traefik; an explicit override must be `docs.aberration.app`.
4. Verify the dashboard created the proxied DNS record for `docs` targeting this
   tunnel's `<tunnel-id>.cfargotunnel.com`. Remove a conflicting `docs` record if
   one already exists. This uses the existing tunnel token and edge HTTPS.
5. Keep this hostname public: it must not inherit a Cloudflare Access login
   requirement from a wildcard application.

See Cloudflare's [published application setup](https://developers.cloudflare.com/tunnel/get-started/)
and [DNS routing](https://developers.cloudflare.com/tunnel/concepts/routing/).
The route may return an error until the first docs service deployment. The
production release checks the docs hostname, so configure the route before that
release runs. After deployment, verify `/`, `/getting-started/`, `/llms.txt` and
`/getting-started.md` at the new hostname.

The separate GitHub Pages workflow has been removed. After verifying the new
hostname, unpublish the old site in the repository's **Settings → Pages**; deleting
the workflow alone does not remove an already published site. The old
`github.io/off-key/` links will stop working after unpublishing; they cannot be
redirected by the production stack. The README, canonical URLs and landing-page
links now use the new hostname. Local preview remains `zensical serve`.

## Logs and Grafana

With `observability_enabled` (production), Alloy collects only Off-key logs on
workers, including dynamic RADAR workers. Loki and Grafana run on the explicitly
selected data worker. Loki keeps seven days on a bounded filesystem. See the
[worker observability runbook](observability.md) for placement, capacity,
independent deployment, verification and pause.

Grafana is at `https://grafana.aberration.app` behind the same oauth2-proxy gate as
the broker and Traefik dashboards. It trusts the GitHub login oauth2-proxy returns
to Traefik, signs members up as editors on first visit, and has no login form,
sign-up or anonymous access. To publish it once, add the `grafana` public hostname
to the existing tunnel in Cloudflare and route it to `http://traefik:80`, like the
other hostnames. Never route it to Grafana directly: Grafana relies on Traefik to
set the identity header.

Start with **Aberration system overview** in the **Aberration** folder. It shows
which workers are delivering logs, how many error lines and RADAR failure
signals Loki saw, and which services are producing warnings and errors. Compare
the worker count with the active Swarm workers. Use the detailed logs link to
investigate a service or run.

Open **Aberration logs** to browse the last seven days of retained worker
container logs. Filter by **Service**, **Worker** and **Level**. The two charts
show the volume within those filters. **Contains** searches the original log
lines in both log panels, ignoring case. It accepts message fragments, request
references and RADAR IDs. Scroll the log panel to load older results, and
expand a line to inspect its text and fields. **Unclassified** includes lines
where Loki could not infer a level.

The separate RADAR panel shows lifecycle events such as stage changes,
calibration and failures. Application services log JSON at INFO. RADAR log
records include `service_id`, `run_id` and `revision_id` for run-scoped
investigation. In Explore, for example:

```logql
{service=~".+"} | json | extra_service_id="<monitoring service id>"
```

A browser error from the API shows a reference such as `(reference 4f1c…)`. It is
the request's correlation ID, so `{service=~".+"} |= "4f1c…"` finds every line of
that request in the API.

Alloy uses a per-node Unix proxy limited to the Docker discovery and log APIs.
No monitoring service publishes a port; only Traefik connects Grafana's internal
network to its existing authenticated route.

## Catalog and private observations

Use authenticated **Sources** to import an `aberration-system` catalogue or edit
brokers, entities and readings. Recording is explicitly opt-in. Operator networking,
credentials and TLS settings remain private and separate from catalogue exports.

Do not reset an existing database during an upgrade; see
[Collection](system-collection.md) for what the catalogue migrations preserve.

Real observations and source registration/recovery notes remain private operator
material. They are not required for hosted CI.

Previously published catalog identifiers remain in earlier public Offkey commits;
this integration replaces the current template without rewriting public history.
