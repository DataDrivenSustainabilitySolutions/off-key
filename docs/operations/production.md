# Production releases

Production runs Docker Swarm from `infra/`. Local development remains Docker Compose;
there is no staging environment. Application, migration and infrastructure files are
released from one tested main commit. See [GitHub setup](github-setup.md) before cutover.

## Release sequence

1. All latest main push attempts for CI, Deployment Smoke, MQTT Collection Integration,
   Infrastructure Validation and Docker Publish must succeed for the same SHA.
2. One GitHub production job connects through an ephemeral management-tailnet runner
   and verified SSH. Superseded automatic candidates stop before deployment.
3. Runtime files are compared against the manager's last verified release. Documentation
   changes do not deploy; intervening undeployed runtime changes remain visible.
4. Deployment uses the exact immutable image digests saved by that SHA's successful
   production rehearsal. OCI revision labels must match the SHA; a missing or expired
   rehearsal artifact blocks deployment. The control checkout must be clean and match
   that same commit.
5. A durable database operation fences monitor start/stop/delete and catalog writes.
   Normal requests receive HTTP 503 during release maintenance.
6. Pending schema migrations require all application writers to stop. A validated
   custom-format backup stays private on the database node. SQL and checksum ledger
   changes commit together under a PostgreSQL advisory lock.
7. Active monitor configurations are saved, their actual old tasks must stop, and
   new UUIDs restart the same monitors with fresh calibration. Pending user stop
   intent is honored. Historical telemetry/evidence remains; old checkpoints are
   never loaded by a new UUID.
8. The stack, image/replica plan, schema/API readiness, collector/catalog routing,
   restarted worker heartbeats and public HTTP routes must pass verification.
   Waiting for charger data is valid. Only then is maintenance completed and
   `release.json` replaced. An interrupted release cannot be replaced by another SHA.

Dispatch a tested release manually with `make deploy-prod REVISION=<full SHA>`.
Use `BOOTSTRAP=true` only for the first integrated cutover. The automatic switch
starts disabled. Production secrets/configuration changes require a manual dispatch.

The workflow captures Ansible output in private temporary files and deletes it with
its configuration at job exit. Database backups, vendor identity, recovery records
and private inventories are not published as Actions artifacts. Investigate live
failures through trusted SSH and the server-side records, not public log uploads.

## Checks before production

Deployment Smoke runs the existing browser and adaptive-monitor journeys against a
disposable Swarm using the production frontend, TLS/authenticated MQTT and deployment
tasks. PRs build production images; main tests the published image digests before
making them eligible for deployment. Synthetic accounts, saved catalog definitions,
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
The vendor identity must exist on the manager's NFS export or be restored from a
private seed before deployment. CI never registers a replacement vendor device.
NFS permits the discovered backend management-tailnet /32 addresses only.

Persistence changes keep the existing explicit confirmation/backup/restore guard.
Automatic CD never supplies confirmation. Do not combine the initial integration
cutover with a persistence flip. Recover state first using [Recovery](recovery.md).

## Credentials, ingress and certificates

The encrypted production vault remains the configuration source. The production
workflow temporarily unlocks it, uses a short-lived GHCR token and deletes runner
files; backend and manager registry sessions log out even on failure. A local
operator may still use an independently stored recovery registry credential.

Cloudflare's existing tunnel routes HTTPS hostnames to Traefik. Configure public
routes/DNS in Cloudflare, matching the committed production hostname settings.
The tunnel token is a versioned Swarm secret. oauth2-proxy limits the broker and
Traefik dashboards to the configured GitHub organization/user allowlist.

EMQX clients use TLS and separate least-privilege users, with credentials mounted as
versioned Swarm secrets. Generate/validate certificate material using
`infra/scripts/generate-emqx-pki.sh` and `validate-emqx-pki.py`; keep private keys in
the encrypted vault. When changing a client password, rotate the existing EMQX user
first; the playbook rejects changing only bootstrap/client values on a running broker.

Production email uses the configured Resend SMTP account with TLS and verified
sender DNS. Save its key as `email_password` in the encrypted vault. First-admin
invitation runs after readiness; `make -C infra invite-admin-prod` can resend it.
Local Compose uses Mailpit. No production Mailpit service remains.

## Catalog and private observations

The bundled AmbiBox catalog is a synthetic template with collection off. Import
real source definitions through authenticated Data sources; saved database catalogs
are preserved across releases. Real fleet observations, university topology and
vendor registration/recovery notes remain private operator material. They are not
required for hosted CI. There is no need for the old Windows or university-network
workstation setup when deploying through the management tailnet.

Previously published catalog identifiers remain in earlier public Offkey commits;
this integration replaces the current template without rewriting public history.
