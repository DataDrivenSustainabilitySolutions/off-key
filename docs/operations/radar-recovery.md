# RADAR recovery

Each RADAR worker stores one signed recovery snapshot in
`radar_runtime_checkpoints`, owned by its `services` row and deleted when that
monitor is deleted. A worker started with `RADAR_DB_WRITE_ENABLED=false` keeps no
snapshot and starts fresh.

A managed snapshot contains the detector, cumulative processing counters and
versioned coverage history. Its signature binds the service ID, monitoring and
alignment configuration, scientific runtime versions, processed count and save
time to the serialized model bytes. Verification and compatibility checks happen
before deserialization. Missing snapshots start a new detector; incompatible or
corrupted snapshots fail startup. Operators must explicitly retire the monitor
and create a new one when fresh calibration is intended.

Production reads `RADAR_CHECKPOINT_SECRET` from its mounted Swarm secret.
Development uses the stable, public key in `.env.example` unless explicitly
overridden. The public development key is rejected in production. Keep the
configured key stable across worker replacements. Key rotation requires a
reviewed recovery/recalibration procedure; changing it invalidates old snapshots.

A monitor reads its input from the stored telemetry log, not from a broker. The
collection worker appends each accepted reading to `telemetry`, and each row takes
the next `log_seq` under one transaction lock, so positions become visible in
order: once a monitor has read a position, no smaller one can still appear. The
monitor reads the rows of its own readings after the position it last processed,
`RADAR_LOG_BATCH_SIZE` at a time, and polls every `RADAR_LOG_POLL_SECONDS` once it
has caught up. A failed read is retried with backoff up to 30 seconds and reports
the monitor unhealthy until a read succeeds. Nothing is dropped for being slow.

The worker checkpoints before it reads the log, at detector phase changes, after
`RADAR_CHECKPOINT_INTERVAL` aligned observations, within
`RADAR_CHECKPOINT_MAX_INTERVAL_SECONDS` (30 seconds by default), and after
stopping its log reader during graceful shutdown. Known coverage changes also trigger
a checkpoint. Pending alarms and evidence commit in the same transaction as the
snapshot, and the snapshot holds the log position of exactly the readings its
state contains: the position advances under the same lock checkpoints take. Failed writes retain pending results and stop further model advancement
after the configured `RADAR_CHECKPOINT_TIMEOUT_SECONDS` (30 seconds by default).
An interrupted static fit restarts from its preserved training and calibration
observations.

This restores the latest committed detector state after task or node replacement,
then replays every reading logged after the snapshot's position: work rolled back
by a hard crash and readings that arrived while the monitor was down are both
processed. Every reading carries the time the collection worker received it, and
the monitor's clocks follow that time while it works through the log, so a
replayed backlog is judged as it was live, the same way a Dojo replay is. Once
caught up, the clocks follow the wall clock, so a silent reading still goes stale. Evidence committed by earlier background
batches can be ahead of the restored detector; its keys are deterministic, so the
replay writes it once. A restore resets partially aligned sensor frames. A new
monitor starts at the newest logged row. Recovery metadata, including the restored
and saved log positions, is included in the worker health metrics and persisted
operational status. These guarantees
depend on the PostgreSQL deployment retaining its data; a node-local worker volume
is not required.

Managed snapshots also retain the highest accepted observation timestamp for each
reading. Replacement workers restore these watermarks while clearing partial
feature vectors. Retained or replayed observations already covered by the snapshot
cannot advance the restored detector; each required reading must produce a newer
observation. Watermarks share the snapshot's log position, so replay after a hard crash
processes each reading once.

A managed snapshot with processed observations but no observation history fails
startup. This revision is unreleased and does not accept an older payload that
would reopen the replay boundary. An initial snapshot before the first
observation may have empty history. Changing the hold intervals, minimum hold
or future-time tolerance invalidates the snapshot. A restored worker keeps the
rejection watermarks and starts over with every reading's latest value and
learned interval.

The signed snapshot signature also fences overlapping managed workers. An initial
snapshot has one database winner, and each later checkpoint must replace the
signature that its writer last loaded or committed. Evidence batches lock and
check that same snapshot row until their transaction finishes. Once another
worker commits a successor, a stale writer cannot commit further checkpoints or
evidence. Ownership loss is terminal: pending results remain queued, new results
are rejected, and the worker stops after observing the loss. This permits
concurrent computation during replacement; it does not provide exclusive
inference.

Health writes check the signature without locking the snapshot row, allowing a
heartbeat to report an evidence transaction blocked in PostgreSQL. During a
simultaneous takeover, operational status remains a health projection based on
the statement's database snapshot rather than a serializable ownership record.

Managed workers serialize feature processing, inference, model health refresh and
checkpoint encoding on one dedicated model thread. The event loop persists
evidence and reports health from complete cached detector snapshots. A slow model
cannot create concurrent inference or prevent the health loop from observing a
stall. Cancellation waits for the active model operation before taking the final
snapshot. The log reader hands one row at a time to the model owner, so a slow
model holds the reader back instead of growing a queue.

## Graph failures and revision rollback

Graph runs bind checkpoints to executable semantics, resolved readings and exact
runtime versions. Cosmetic layout changes do not invalidate numerical recovery.
Returning to an earlier published revision creates a fresh run and calibration;
it does not restore a checkpoint from a different bound revision.

A fatal uncertain update quarantines the worker immediately. It performs no more
graph calls and exports no checkpoint, including during shutdown. The managed
worker persists failed-run status under the existing signed-snapshot ownership
lock before exiting. If this write times out, it remains quarantined and retries
until the database returns or an explicit stop terminates it. A committed failed
run fences admission of that execution generation. Its last signed snapshot stays
intact and its failed-node diagnostics and coverage remain inspectable.

The failure write checks signed-checkpoint ownership and the exact run/service
identity. Every activated successor has a new service and run identity. A fatal
update discovered while its own run is stopping may still be recorded as that
run's terminal failure; it cannot fail the successor. Delayed task admission also
checks durable lifecycle intent and rejects terminal run generations.

A host/process loss before the failure record commits is indistinguishable from
an ordinary crash. Existing recovery can restore only the last authenticated
committed snapshot and reports the possible coverage gap. It never restores the
uncommitted, damaged in-memory graph. Operators requiring a fresh run can activate
the same revision again rather than recovering the previous run.

Ship pipeline-compatible runtime/schema support before enabling authoring. Turning
authoring off does not disable existing graph execution, inspection or stopping.
Software rollback requires a binary from the same schema baseline or the reviewed
database restore procedure. Binaries from before the baseline cannot read its
migration ledger or graph launch contracts.
