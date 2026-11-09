# Cut over to Aberration

This release renames the Python distributions/modules, repository references,
container images, deployment variables, Swarm resources, database routines,
authentication identifiers and observability paths. It is a coordinated maintenance
release. Do not run the old and new applications together against one database.

The PR changes source and defaults only. It does **not** rename GitHub, change your
private secrets, move live volumes or delete a running installation. The commands
below are operator actions for the cutover, after CI passes. Keep a private record
of the old commit, exact images, service specifications, mounts and backup locations.

## 1. Prepare accounts and the release

1. Set the GitHub production environment variable `AUTO_DEPLOY_ENABLED=false` and
   repository variable `GHCR_RETENTION_ENABLED=false`. Wait for any deployment to
   finish. Record the last verified production SHA and preserve its images.
2. Rename `DataDrivenSustainabilitySolutions/off-key` to
   `DataDrivenSustainabilitySolutions/aberration` in GitHub settings. Update local
   remotes with `git remote set-url origin
   https://github.com/DataDrivenSustainabilitySolutions/aberration.git`.
3. Create the following **production environment** secrets from your independent
   recovery material. GitHub cannot return the values of existing secrets.

   | Previous secret | New secret |
   | --- | --- |
   | `OFFKEY_PROD_VAULT` | `ABERRATION_PROD_VAULT` |
   | `OFFKEY_VAULT_PASSWORD` | `ABERRATION_VAULT_PASSWORD` |
   | `OFFKEY_PROD_INVENTORY` | `ABERRATION_PROD_INVENTORY` |
   | `OFFKEY_DEPLOY_SSH_KEY` | `ABERRATION_DEPLOY_SSH_KEY` |
   | `OFFKEY_DEPLOY_KNOWN_HOSTS` | `ABERRATION_DEPLOY_KNOWN_HOSTS` |

   Preserve credential values. Upload the reviewed encrypted vault and inventory,
   including any naming changes described below. `TS_OAUTH_CLIENT_ID`, `TS_AUDIENCE`
   and the `production` environment name do not change merely because of this rename.
4. In the management Tailscale federated identity, change the repository claim,
   subject to `repo:DataDrivenSustainabilitySolutions/aberration:environment:production`
   and workflow claim to
   `DataDrivenSustainabilitySolutions/aberration/.github/workflows/deploy-production.yml@refs/heads/main`.
   Retain the main-branch and numeric repository/owner restrictions. Add
   `tag:aberration-ci`, give it the existing narrowly scoped deployment permissions,
   and authorize the identity to issue this tag. Retire `tag:offkey-ci` after success.
5. Merge the rename PR with automatic deployment still disabled. Wait for the
   **main push** CI to publish and rehearse all six `aberration-*` application images.
   Verify package Actions access for the renamed repository. The committed manifest
   uses `unpublished`/`:latest` as repository selectors until this happens; they are
   deliberately not fabricated digest pins. Deployment resolves the successful
   main run's `production-release` artifact and requires actual immutable digests.
6. Preserve the custom GitHub Pages domain and verify its next publish. Public
   `aberration.app`, `dashboard.aberration.app`, `docs.aberration.app`, DNS, Cloudflare
   Tunnel and the OAuth callback URL already match and need no branding change.

Do not repurpose the old GitHub repository name while redirects are needed.

## 2. Review private configuration

For dotenv files, preview without printing secrets, then write a separate private
candidate (the tool refuses to overwrite any existing file):

```bash
python3 infra/scripts/rename_environment.py /private/path/current.env
python3 infra/scripts/rename_environment.py /private/path/current.env \
  --output /private/path/aberration.env
```

The helper accepts single-line dotenv values and refuses multiline values for
manual review. It renames `OFFKEY_*` keys and known identity values; it preserves password,
token, checkpoint-secret and arbitrary JSON credential values. It does not move
the database or Docker resources. Keep the old configuration until cutover succeeds.

Review YAML inventory/vault overrides separately, including:

| Identity | New value |
| --- | --- |
| `offkey_env` variable | `aberration_env` (keep its value, normally `prod`) |
| `stack_name` | `aberration` |
| `stack_dir` | `/opt/stacks/aberration` |
| application image repositories | `ghcr.io/datadrivensustainabilitysolutions/aberration-*` |
| TACTIC networks | `aberration_emqx-network`, `aberration_app-network` |
| MQTT proxy/radar usernames | `aberration-proxy`, `aberration-radar` |
| MQTT client ID prefix | `aberration-backend` |
| Grafana local administrator | `aberration_local_admin` |
| observability data root | `/srv/aberration-observability` |
| observability mount root | `/var/lib/aberration-observability` |

The checked-in production database is named `postgres`; keep that name. A local
database named `off_key` needs an actual database rename or a logical restore into
`aberration` before using `POSTGRES_DB=aberration`. Changing the variable alone
does not rename an existing database. Preserve node names, external broker accounts,
vendor hostnames, CA material, signing secrets and the broker-route node identity.

EMQX bootstrap users are not changed by redeploying against persisted data. Create
the new proxy/radar users with their existing passwords and equivalent ACLs in
EMQX before the switch. Update any username-specific rules. Rename Grafana's saved
local administrator through Grafana; changing its bootstrap variable does not
rename an existing account. Remove old accounts only after verification.

## 3. Back up and quiesce the old installation

Use a separate checkout of the last verified **old** release and its matching private
inventory/vault for old-stack backup/recovery commands. Keep it out of the new PR.

1. Put the public application into maintenance and stop incoming collection as
   appropriate. Record service replica counts and all dynamically created RADAR/
   preflight workers, including services outside the stack namespace. Record the
   node hosting each stateful task and every named-volume/bind mount.
2. Stop old TACTIC, proxy, replay/Dojo and RADAR writers. Wait for their tasks to
   exit. Stop the old observability services before copying their state.
3. With PostgreSQL and EMQX still available, use the old checkout's
   `make -C infra backup-stack-prod` and `backup-broker-route-prod`. Because writers
   were already stopped, their recorded counts must remain zero. Verify the
   complete backup manifests/checksums and restore into an isolated disposable
   database before proceeding. Save roles, all databases, broker data and logs,
   broker-route `tailscaled.state`, Grafana/Loki data and the old release records.
4. Stop the remaining stateful services cleanly. Only after verified backups and
   a complete mount inventory, remove the old stack services and separately managed
   old workers. Wait for every old task/container to exit. Stack removal does not
   migrate or remove its volumes. The new deployment explicitly refuses to proceed
   while any service in the `off-key` stack remains.

Do not use `docker system prune --volumes` or `docker compose down -v` as migration
steps. Old services and writable container layers must not be removed before
backups are complete; not every installation is guaranteed to use persistent mounts.

## 4. Move persistent state while offline

Perform these operations on the **actual node holding each volume**, not just the
manager. Keep PostgreSQL/TimescaleDB and EMQX versions unchanged for this cutover.

| Existing resource | Replacement |
| --- | --- |
| `off-key_postgres_data` | `aberration_postgres_data` |
| `off-key_emqx_data` | `aberration_emqx_data` |
| `off-key_emqx_log` | `aberration_emqx_log` |
| `/opt/stacks/off-key` runtime state | `/opt/stacks/aberration` runtime state |
| `/srv/offkey-observability` | `/srv/aberration-observability` |
| `/var/lib/offkey-observability` mount | `/var/lib/aberration-observability` mount |

This table is a mapping, not an inventory. Include any additional discovered
volumes and custom bind paths. Copy stopped local-volume contents into new volumes,
preserving ownership, modes, symlinks and extended attributes; compare checksums.
Alternatively restore the verified logical backups using the recovery runbook.
Never attach the same database directory to two running PostgreSQL containers.
If using node-local volumes, retain/pin the original stateful service placement so
the new task cannot start against an empty volume on another node.

On the manager, copy the broker-route state into the new `stack_dir`, using
the subdirectory selected by `broker_route_state_dir` in the private inventory. Preserve the existing node identity and
permissions. Update the NFS export path and remove the old export after it has no
clients. Recreate the route's NFS-backed Docker volume with the new `device` path;
copying its Docker volume name is insufficient because Docker retains driver
options. The route must never enroll as a second identity.

Move observability's filesystem/mount configuration and update any host fstab or
systemd references before starting Grafana/Loki. Preserve existing historical logs
and dashboards; historical log labels remain historical facts. Reimport provisioned
dashboards so new queries use `stack="aberration"`.

Copy recovery backups separately. Do not seed the new stack directory with stale
`release-maintenance.json`, `recovery-pending.json`, `release-pending.json`, generated
Compose files, or a misleading verified `release.json`. Resolve any interrupted
old operation first, and retain its records in the private recovery archive.
Ansible renders fresh configuration and records the new verified release itself.

For a local database-name change, after stopping its clients and connecting to a
different database (for example `template1`), use:

```sql
ALTER DATABASE off_key RENAME TO aberration;
```

Then select that database in the new dotenv file. If the private configuration uses
a different database name, preserve it instead of applying this example blindly.

## 5. Deploy the tested release and verify

Dispatch **Deploy Production** on `main` with the successful main push's full SHA
and `bootstrap=true`. That controlled deployment must see the restored database,
not an empty replacement. Migration 026 and the normal deployment flow:

- validate the old ledger's unchanged checksums and rename the ledger and its key;
- replace evidence/anomaly functions and remove obsolete retention jobs/procedures;
- preserve accounts, telemetry, evidence, catalogue, pipelines and monitor definitions;
- revoke remembered sessions and discard old signed/pickled detector checkpoints;
- restart monitors with fresh calibration through the existing maintenance protocol.

Users must sign in again and reload old tabs. Browser draft/chart-navigation storage
is copied to the new keys on startup, without overwriting newer values; old keys
are removed only after copying succeeds. Save important drafts before maintenance
because signing out can clear account-scoped drafts. No compatibility shim accepts the old API
headers, cookies or JWT identity after the cutover.

Verify login/refresh/logout, catalogue browsing, incoming MQTT and stored telemetry,
monitor creation/start/stop, new anomaly evidence, Dojo/replay, pipeline activation,
email delivery, broker-route access, dashboards/log ingestion and the docs site.
Restart a monitor and verify a **new-format** checkpoint restores. Check data counts
against the backup and verify the new release record and absence of pending
maintenance. Confirm no old workers or old database functions/jobs remain.

## 6. Rollback boundary and cleanup

This identity migration is **not binary-compatible with pre-rename releases**.
The CI binary-rollback fixture starts at the renamed schema. To return to the old
application, stop all new writers, restore the pre-cutover database and broker
backups, restore the old stack configuration/identities and run the old release's
recovery procedure. Merely selecting an old image is not a valid rollback. Account
for writes accepted after cutover before choosing a backup restore.

After acceptance and an agreed recovery retention period:

1. Remove old stopped containers, workers, stack networks, secrets/configs and
   old volumes **by the reviewed inventory**, after confirming none are mounted
   or referenced and backups exist. Do not blanket-prune the shared engine.
2. Remove old GHCR `off-key-*` packages and local images after preserving the
   recovery release for the retention period. The new retention job manages only
   `aberration-*`; it intentionally does not delete the old namespace for you.
3. Remove old GitHub secret names, Tailscale tags/trust rules, EMQX users/ACLs,
   obsolete NFS exports, old observability mounts and obsolete runtime directories.
4. Rename local checkouts. Repair registered worktrees with `git worktree repair`
   from the moved main checkout. Recreate both `.venv` directories with `uv sync`
   (backend: `--all-packages --all-groups --frozen`; infra: `--frozen`) because
   executables and editable installs contain absolute paths. Update editor/task
   project paths and any personal shell scripts. Use `npm ci` for the frontend.
5. Migrate each local Compose project's data before changing its project name.
   `dev/local/.env` persists the old path-derived project name and image names;
   use the helper, then verify the replacement resources before deleting the old.
6. Resolve and commit the first verified release pins with
   `uv run --project infra python infra/scripts/pin_release.py <verified-main-SHA>`.
   This replaces the initial repository selectors with real published digests and
   protects the recovery release from registry retention.
7. Re-enable `AUTO_DEPLOY_ENABLED`, and enable `GHCR_RETENTION_ENABLED` only after
   reviewing the new namespace's retention dry run.

The remaining old-name literals in source are intentional historical SQL,
the identity-upgrade reader/cleanup, historical checkpoint capture tooling and
tests, and this cutover guide. Released migration bytes/checksums, Git history,
historical logs and recovery backups are not rewritten to remove a brand name.
