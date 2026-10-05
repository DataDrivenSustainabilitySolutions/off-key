# Recovery

A failed release keeps the previous verified `release.json`. The attempted release
is in `release-pending.json`; `release-maintenance.json` and the database's
`deployment_maintenance` singleton identify incomplete work. Catalog and monitor
mutations stay blocked until the operation completes. Do not clear these records
just to make a newer release run.

## Retry the interrupted release

1. Set `AUTO_DEPLOY_ENABLED=false` while investigating.
2. Read the attempted SHA through verified SSH. Inspect `docker service ls`, failed
   task state and service logs privately. Check `recovery-pending.json` too.
3. Fix the external cause (connectivity, disk space, access or registry availability),
   rerun failed main checks if needed, and manually dispatch **the same tested SHA**.
   Use the original bootstrap setting. Completed migrations validate their checksums;
   completed monitor stops/restarts are resumed without creating duplicate workers.
4. Verify the public app, catalog and monitors. Reenable automatic deployment only
   when the release succeeds and its operation is complete.

Database migration failures roll back their transaction. The pre-upgrade backup is
`/opt/stacks/off-key/.backup/releases/<SHA>/database.dump` on the database node,
with a checksum alongside it. A retry never overwrites that original backup.
Backups are mode 0600 in a 0700 directory and are validated before applying SQL.
Keep independently encrypted off-server backups through your private backup process;
the deployment job deliberately does not transfer production dumps to GitHub.

## Roll back a completed release

Dispatch a previously green **integrated** main SHA with bootstrap unchecked.
The workflow checks its own tests, image labels and infrastructure commit. The
migration ledger rejects unknown/newer or changed migrations and incompatible schemas.
A code rollback is permitted only when that target can validate the current database.
A release older than this integration cannot run the integrated recovery machinery.

There is **no automatic database downgrade**. If schema restoration is necessary,
use a maintenance window, stop all writers and restore a verified backup before
starting an older application. Restoring a database loses writes newer than the
backup. Select a reviewed recovery procedure and reconcile the maintenance records
with the actually restored database; do not pretend this is a routine code rollback.

## Existing backup and restore tools

With private local inventory/vault and a verified management SSH connection:

```sh
make -C infra backup-stack-prod
make -C infra backup-ambibox-prod
make -C infra restore-stack-prod TS=<explicit-backup-timestamp> SERVICES=postgres,emqx
```

These explicit operator tools may transfer backups to the ignored local
`infra/stack/state/prod/` directory. They are separate from automatic releases.
A persistence restore resumes writers only after it verifies the replacement task
and restored state. An interrupted persistence recovery must finish before CD retries.

Each PostgreSQL/EMQX backup publishes `manifest.json` last, after every expected
artifact has reached the control host. The manifest records the service, timestamp,
exact artifact names and SHA-256 checksums. Restore verifies every listed artifact
before stopping any service and restores only that list. A directory without a
manifest is incomplete, even if it contains `roles.sql` and some database dumps.
Take a new complete backup instead of using those artifacts. Older backups and
older pending plans require a separately reviewed recovery procedure; do not add a
manifest by guessing which databases should have been captured.

An interrupted cutover's `recovery-pending.json` records its original timestamp,
complete backup references, required services, writer counts and replacement-task
checks. Retry with **that timestamp and exactly that service set**. For example, an
EMQX-only cutover requires `SERVICES=emqx`, including a log-only persistence change.
An unrelated backup or a subset cannot clear the transaction. A failed retry keeps
the original plan and writer counts; successful recovery clears it only after the
entire recorded service set has restored.
If an additional runtime writer is running outside that original plan, recovery
refuses to change any writers or restore data. Stop the unexpected writer before
retrying; additional stopped workers stay stopped and are not added to the plan.

A backup failure before stateful replacement cancels the cutover, resumes the
original writers and clears its plan only after resumption succeeds. If resumption
also fails, the backup-phase plan remains: some writers may already be running.
Verify that the original stateful tasks and data are intact, restore the recorded
writer counts, then clear that backup-phase plan. Do not restore its incomplete
artifacts. If a failure occurred after replacement began, keep writers stopped and
ensure the intended replacement tasks and mounts are running before retrying the
recorded restore; the restore command validates them before importing data.

Preserve the vendor NFS identity and private access material independently. Restore
an identity only after fencing its former holder; do not run two vendor nodes from
one copied identity. Missing identity fails deployment until explicitly restored.
Keep vault password, SSH recovery access, known-host fingerprints and database/vendor
backups outside GitHub so recovery remains possible if GitHub is unavailable.
