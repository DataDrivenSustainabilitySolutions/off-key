# Recovery

A failed release keeps the previous verified `release.json`. The attempted release
is in `release-pending.json`; `release-maintenance.json` and the database's
`deployment_maintenance` singleton identify incomplete work. Catalog and monitor
mutations stay blocked until the operation completes. Do not clear these records
just to make a newer release run; complete them as described below.

## Retry the interrupted release

1. Set `AUTO_DEPLOY_ENABLED=false` while investigating.
2. Read the attempted SHA through verified SSH. The release issue names the failed
   task and readiness check; the release's full log is the newest file in
   `<stack_dir>/release-logs/`. Inspect `docker service ls`, failed task state and
   service logs privately. Check `recovery-pending.json` too.
3. Fix the external cause (connectivity, disk space, access or registry availability),
   rerun failed main checks if needed, and manually dispatch **the same tested SHA**.
   Use the original bootstrap setting. Completed migrations validate their checksums;
   completed monitor stops/restarts are resumed without creating duplicate workers.
   After a [database reset](production.md#schema-baseline-and-database-reset),
   retry without `RESET_DATABASE`: the database is already empty or on the
   baseline, and the reset's backup stays where it was saved.
4. Verify the public app, catalog and monitors. Reenable automatic deployment only
   when the release succeeds and its operation is complete.

Database migration failures roll back their transaction. The pre-upgrade backup is
`/opt/stacks/off-key/.backup/releases/<SHA>/database.dump` on the database node,
with a checksum alongside it. A retry never overwrites that original backup.
Backups are mode 0600 in a 0700 directory and are validated before applying SQL.
Keep independently encrypted off-server backups through your private backup process;
the deployment job deliberately does not transfer production dumps to GitHub.

## Complete a release whose own verification is defective

A retry runs the attempted SHA's own code, so a defect in its verification fails
every retry while the guard refuses a fixed SHA. When every check before the failed
step passed (convergence, readiness, restarted monitors and public routes), complete
that release's operation through trusted SSH instead:

1. Set `AUTO_DEPLOY_ENABLED=false`.
2. On the node running the stack's TACTIC task, run
   `docker exec <container> /app/bin/python -m off_key_tactic_middleware.deployment status <SHA>`.
   It must report that SHA in phase `restarted`.
3. Run the same command with `finish`. It verifies every restarted monitor again,
   then opens catalog and monitor changes.
4. On the manager, rename `<stack_dir>/release-maintenance.json` to
   `release-maintenance.<SHA>.json`. `release.json` keeps the last fully verified
   release, so the fixed release compares its runtime changes from there.
5. Merge the fix and deploy its SHA, then reenable automatic deployment.

## Abandon a release whose monitors cannot recover

When the attempted SHA itself keeps restarted monitors from reporting healthy, so
neither a retry nor `finish` can succeed, abandon its operation instead of leaving
catalog and monitor changes blocked:

1. Set `AUTO_DEPLOY_ENABLED=false`.
2. On the node running the stack's TACTIC task, run
   `docker exec <container> /app/bin/python -m off_key_tactic_middleware.deployment abort <SHA>`.
   Monitors the release restarted keep running as they are; the output lists them
   under `restarted`. Monitors it stopped but did not restart stay stopped and are
   listed under `not_restarted`; start them again from the workbench.
3. Rename `<stack_dir>/release-maintenance.json` as in step 4 above, deploy a fixed
   or earlier SHA, and reenable automatic deployment.

## Roll back a completed release

Dispatch a previously green **integrated** main SHA with bootstrap unchecked.
The workflow checks its own tests, image labels and infrastructure commit. The
migration ledger rejects unknown/newer or changed migrations and incompatible schemas.
A code rollback is permitted only when that target can validate the current database.
A release older than this integration cannot run the integrated recovery machinery.

### Rolling back past the broker route release

The release that made the broker route source-agnostic replaced production's
source-specific node service (listed in the production inventory as
`stack_replaced_services`) with `broker-route`, and stops the old service before
the new one starts. An older release does not know `broker-route`, keeps it
running and starts its own node from the same identity. After the first verified
deploy of that release, remove the identity export group that older releases
require (named next to `stack_replaced_services`) from the private production
`hosts.yml` (the `OFFKEY_PROD_INVENTORY` secret). Older releases then stop at
their inventory check before they change the stack. To roll back past it anyway:

1. Set `AUTO_DEPLOY_ENABLED=false`.
2. On the manager, run `docker service rm off-key_broker-route`.
3. On every backend node, repeat
   `docker ps -q --filter label=com.docker.swarm.service.name=off-key_broker-route`
   until it prints nothing.
4. On the manager, run
   `rm /etc/exports.d/broker-route.exports && exportfs -ra`; the older release
   writes its own export file for the same directory.
5. Add the manager back to that group and keep the login file the older release
   reads on the manager (named in the production inventory next to
   `broker_route_legacy_exports_file`). Then dispatch the older SHA.

### Rolling back past the HTTP source release

A catalogue without HTTP sources is stored exactly as before, so this rollback
needs nothing extra. Releases before HTTP sources cannot read a saved catalogue
that holds an HTTP API or a reading with a source timestamp: their catalogue
and recording requests fail. Before dispatching such a release, remove every
HTTP API under **Sources** (its readings go with it) and wait until recording
reports the change as applied. Recorded history stays in the database.

There is **no automatic database downgrade**. If schema restoration is necessary,
use a maintenance window, stop all writers and restore a verified backup before
starting an older application. Restoring a database loses writes newer than the
backup. Select a reviewed recovery procedure and reconcile the maintenance records
with the actually restored database; do not pretend this is a routine code rollback.

## Existing backup and restore tools

With private local inventory/vault and a verified management SSH connection:

```sh
make -C infra backup-stack-prod
make -C infra backup-broker-route-prod
make -C infra restore-stack-prod TS=<explicit-backup-timestamp> SERVICES=postgres,emqx
```

These explicit operator tools may transfer backups to the ignored local
`infra/stack/state/prod/` directory. They are separate from automatic releases.
A persistence restore resumes writers only after it verifies the replacement task
and restored state. An interrupted persistence recovery must finish before CD retries.
Backups are staged on the database or broker node only for the transfer and removed
from it once the control host holds them or the restore finishes.

Restoring the application database from a backup ends every session it carried:
each account's session version is raised and remembered sessions are deleted, so
sessions revoked after the backup was taken cannot come back. Everyone signs in
again. Passwords, roles and invitations return to their state at backup time, so
review accounts changed since then.

Alarms live in a TimescaleDB hypertable, and each one's public identifier refers to
it by a foreign key. The restore adds the foreign keys of ordinary tables last, with
TimescaleDB active for that step alone and its background jobs still stopped, so the
key is checked against every chunk of alarms before retention can delete one. An
earlier restore added that key with everything else and stopped at
`postgres | restore each database` as soon as the backup held one alarm. Such a
backup is complete: only the restore changed, so restore it with the current
playbooks.

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
Zero desired replicas do not prove a worker has stopped: Swarm may still have a
retiring task. Recovery waits for every task of an additional zero-replica worker
to become terminal before changing original writers or importing data. If that
wait fails, the saved plan and original writers remain unchanged.

A backup failure before stateful replacement cancels the cutover, resumes the
original writers and clears its plan only after resumption succeeds. If resumption
also fails, the backup-phase plan remains: some writers may already be running.
Verify that the original stateful tasks and data are intact, restore the recorded
writer counts, then clear that backup-phase plan. Do not restore its incomplete
artifacts. If a failure occurred after replacement began, keep writers stopped and
ensure the intended replacement tasks and mounts are running before retrying the
recorded restore; the restore command validates them before importing data.

Preserve the broker route's NFS node identity independently; its MQTT login lives
in the vault. Restore an identity only after fencing its former holder; do not run
two route nodes from one copied identity. Missing identity fails deployment until
explicitly restored.

Keep vault password, SSH recovery access, known-host fingerprints and database/route
backups outside GitHub so recovery remains possible if GitHub is unavailable.
