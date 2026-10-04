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

Preserve the vendor NFS identity and private access material independently. Restore
an identity only after fencing its former holder; do not run two vendor nodes from
one copied identity. Missing identity fails deployment until explicitly restored.
Keep vault password, SSH recovery access, known-host fingerprints and database/vendor
backups outside GitHub so recovery remains possible if GitHub is unavailable.
