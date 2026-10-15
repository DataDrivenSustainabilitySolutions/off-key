# RADAR recovery

TACTIC starts managed workers with `RADAR_CHECKPOINT_STORAGE=database`. Each
worker stores one signed recovery snapshot in `radar_runtime_checkpoints`, owned
by its `services` row and deleted when that monitor is deleted. Apply migration
008 before launching these workers. Standalone detectors retain their file
checkpoint API and default to `RADAR_CHECKPOINT_STORAGE=file`.

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

The worker checkpoints before subscribing, at detector phase changes, after
`RADAR_CHECKPOINT_INTERVAL` aligned observations, within
`RADAR_CHECKPOINT_MAX_INTERVAL_SECONDS` (30 seconds by default), and after
stopping ingestion during graceful shutdown. Known coverage changes also trigger
a checkpoint. Pending alarms and evidence commit in the same transaction as the
snapshot. Failed writes retain pending results and stop further model advancement
after the configured `RADAR_CHECKPOINT_TIMEOUT_SECONDS` (30 seconds by default).
An interrupted static fit restarts from its preserved training and calibration
observations.

This restores the latest committed detector state after task or node replacement.
A hard crash can roll back work since that snapshot. Evidence committed by earlier
background batches can be ahead of the restored detector. Current MQTT input is a
live stream: observations missed during downtime or rolled-back processing are not
replayed. Recovery reports this possible coverage gap, resets partially aligned
sensor frames, and requires new sensor observations. Recovery metadata is included
in the worker health metrics and persisted operational status. These guarantees
depend on the PostgreSQL deployment retaining its data; a node-local worker volume
is not required.

Managed snapshots also retain the highest accepted observation timestamp for each
reading. Replacement workers restore these watermarks while clearing partial
feature vectors. Retained or replayed observations already covered by the snapshot
cannot advance the restored detector; each required reading must produce a newer
observation. Watermarks share the snapshot's rollback boundary, so they do not
provide exactly-once processing after a hard crash. Receipt clocks are local to
the current worker and include time spent waiting in its ingress queue.

A managed snapshot with processed observations but no observation history fails
startup. This revision is unreleased and does not accept an older payload that
would reopen the replay boundary. An initial snapshot before the first
observation may have empty history. Standalone file checkpoints restore detector
state and report a possible restart gap; their detector-only payloads do not
preserve processor observation watermarks. Changing freshness, age, future-time
tolerance or alignment-skew policy invalidates both managed and file snapshots.

Managed workers serialize feature processing, inference, model health refresh and
checkpoint encoding on one dedicated model thread. The event loop persists
evidence and reports health from complete cached detector snapshots. A slow model
cannot create concurrent inference or prevent the health loop from observing a
stall. Cancellation waits for the active model operation before taking the final
snapshot. The MQTT network thread admits messages into a bounded Janus queue,
without scheduling one unbounded asyncio callback per incoming observation.
