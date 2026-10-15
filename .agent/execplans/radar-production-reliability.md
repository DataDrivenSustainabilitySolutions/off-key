# RADAR production reliability

## Objective and scope

Resolve the ten findings from the production RADAR review on main 79e51c4,
one issue at a time with separately reviewable commits, then open one PR.
`.agent/PLANS.md` is absent; this file records the execution plan directly.
Keep existing single-organization, generic catalogue and Swarm deployment contracts.

## Design

Preserve the typed shared configuration and detector boundaries. Establish one
MQTT connection owner, scoped alarm identity, durable signed checkpoint storage,
explicit coverage status, recoverable desired workload state, short database
transactions and bounded serial processing. Cold recovery must report input gaps;
do not claim exactly-once replay from telemetry timestamps. Align observations by
validated observation time as well as receipt time.

## Sequential work

- [x] 1. Fix reconnect ownership and client teardown; real MQTT regression.
- [x] 2. Scope alarm identity by monitoring service; upgrade and real DB regression.
- [x] 3. Persist signed checkpoints across task/node replacement; real restart test.
- [x] 4. Make rate/overflow/restart coverage gaps explicit and remove unsuitable defaults.
- [x] 5. Persist desired workload state before Docker mutation and recover interruption.
- [x] 6. Degrade health when required input or successful inference stops progressing.
- [x] 7. Require successful SUBACKs before readiness, including reconnects.
- [x] 8. Move external workload inspection outside database locks/transactions.
- [x] 9. Bound thread-to-loop ingestion and run detector work serially off the loop.
- [x] 10. Validate observation age, regression, duplicates and cross-sensor skew.
- [x] Reconcile runtime resource budgets, documentation and deployment contracts.
- [ ] Run real MQTT/PostgreSQL/Swarm integration, affected root checks and review.
- [ ] Push the branch and open/attach the PR.

## Validation strategy

Add meaningful regression tests for each issue, retaining boundary mocks only in
unit tests. Final confidence must come from real MQTT, TimescaleDB and Swarm
workloads using current source/images: connection failure and ACL rejection,
independent alarms with shared timestamps, checkpoint recovery in a replacement
task, overload and sensor stalls, interrupted creation, heartbeat concurrency,
bounded ingress under slow inference and delayed observations. Use disposable
resources with an explicit review label; preserve existing local deployments.
Run Ruff, affected backend/frontend tests, builds when public contracts change,
schema upgrade checks and final independent review. Record limitations honestly.

## Progress and decisions

2026-10-15: Clean main updated and branched to codex/radar-production-reliability.
Design analysis is delegated read-only; implementation and commits remain sequential.
Prior baseline: 304 scoped tests and 2 database integration tests passed; real failure
probes reproduced reconnect, subscription, alarm identity, coverage and alignment bugs.

Step 1: Paho automatic reconnection is disabled; RADAR retires and joins each old
client before replacement, rejects callbacks from retired clients and cleans up
cancelled connections. A locked test-only aMQTT broker regression performs three
actual socket failures and verifies one subscription, one delivery and no remaining
network threads. Existing boundary tests now identify the actual disconnecting client.
An independent review also caught initial-start cancellation cleanup; a real TCP
connection withholding CONNACK now verifies cleanup of both network and consumer.

Step 2: Added service-scoped alarm identity and migration 007, preserving historical
public IDs and empty legacy/manual scope. API joins and chart attribution use the
scope. Validation: 71 backend tests including real TimescaleDB writes, retry,
independent deletion and legacy migration with/without a ledger; 18 frontend tests,
TypeScript build and affected Ruff checks pass. Historical discarded alarms cannot
be reconstructed automatically.

Step 7: Broker acknowledgements gate readiness for every required topic. Paho's
current callback API handles acknowledgement rejection, local subscription errors,
timeouts and reconnects. Four real network regressions and 29 async boundary tests
pass. Independent fixes are prepared in parallel and committed per finding.

Step 4: Aggregate throttling is opt-in (zero disables it). Thread-safe cumulative
coverage counters survive log suppression and checkpoints; known drops and possible
disconnect/restart gaps stay visible after traffic resumes. The status API and UI
show the live-only delivery contract. Validation: 99 backend tests including real
1,100-message bursts, exact overflow and reconnect accounting; 48 frontend tests,
TypeScript and Ruff pass. Recovery status contracts are included as preparation for
the checkpoint fix.

Step 3: Migration 008 adds a shared database checkpoint contract with cascading
monitor ownership. Managed workers authenticate service/config/runtime-bound model
bytes before deserialization, restore cumulative processor/coverage state, preserve
and restart static fitting inputs, and checkpoint initial/phase/interval/final
state. The writer atomically commits snapshots with pending evidence and retains
failed batches. A hard crash has bounded checkpoint rollback and a visible live
input gap; no replay/exactly-once guarantee is claimed. Production uses mounted
secrets; local replacements share an explicit development-only key. Step 5 must
persist monitor intent before worker startup because initial snapshots reference
that monitor. Separate real Python replacement processes reproduce future static
and adaptive scores after restoring the database snapshot; actual PostgreSQL
rollback tests verify that evidence and checkpoint advancement cannot split.

Step 5: Durable versioned desired state commits before external workload creation.
Controllers adopt deterministic names only after verifying deployment, service,
generation and configuration labels. Delayed workers check database admission
before initializing detection or subscribing; stop/delete intent fences old
generations. Pending failures remain visible and keep their input claim. Automatic
orphan cleanup is restricted to the database and Docker network namespace.
Validation: 88 lifecycle/upgrade tests including real TimescaleDB and Swarm, plus
an isolated RADAR-only environment import test. Migration 009 is additive; the
historical catalogue converter runs after additive DDL in the same transaction
without changing its recorded checksum.

Step 9: A bounded Janus bridge admits at most 256 messages of 64 KiB by default
before asyncio notification; oversize/overflow/shutdown losses are counted. One
dedicated model thread owns processing, health refresh and snapshot encoding;
health reads complete cached snapshots without waiting for that thread. Shutdown
waits for in-flight model/evidence work. Validation: 44 MQTT regressions including
real broker bursts; a 20,000-observation paused-loop burst holds eight queued
messages/eight wakeups with an eight-entry queue; real detector serial ownership,
34 processor/lifecycle regressions, and 16 checkpoint/runtime tests (real DB and
replacement processes) pass.

Resource budget follow-up: shared strict quantity parsing rejects malformed/zero
Docker limits and reservations; worker soft memory defaults to384MiB below the
512MiB hard limit. Swarm reserves configured CPU/memory (limits by default), and
admission limits active/pending monitors under the sensor claim lock. Typed ingress
bounds are forwarded by TACTIC and cannot consume the entire soft target as raw
payload bytes. The database pool remains bounded at2 connections so a heartbeat
can report an evidence transaction blocked in PostgreSQL. Capacity documentation
requires profiling fitting/checkpoint peaks and does not infer model memory from
arbitrary window parameters. Validation:90 affected tests pass, including real
PostgreSQL concurrent admission and a real Swarm oversized CPU reservation retained
as pending. Existing production-secret workload regression asserts both resource
limits and reservations.

Step 6: Thread-safe activity clocks distinguish valid input receipt, primary
processing, actual inference and committed evidence. Health ages every required
sensor even during silence, retains training progress, and exposes persistence
backlog stalls independently of heartbeat timestamps. Validation: eight focused
activity tests including a real MQTT/Aberrant pause/recovery and actual blocked
PostgreSQL evidence commit with a concurrent health heartbeat; 34 frontend tests
and TypeScript pass.

Step 8: Reconciliation snapshots and commits before bounded Docker probes, then
re-reads each row briefly to compare generation, intent and workload identity.
Newer heartbeats survive stale observations. Collection edits release catalogue
locks while stopping monitors and revalidate both revisions before applying.
Sensor claims remain held until actual Swarm tasks stop, including tasks left
running after external service deletion. Validation: 136 affected unit/SQLite
tests and four real PostgreSQL/Swarm scenarios cover heartbeat concurrency,
delayed termination, residual tasks and concurrent catalogue edits.

Step 10: Observation age, future tolerance, strict per-reading timestamp progress
and cross-sensor skew are validated before advancing the model or input-health
clocks. Receipt freshness includes time spent in the bounded ingress queue.
Managed signed checkpoints retain observation watermarks and discard incomplete
vectors on restore, so retained MQTT input cannot replay already checkpointed
observations. File snapshots bind the same policy but retain their documented
detector-only recovery boundary. Validation: 51 affected unit/alignment/config
tests and 29 real MQTT/PostgreSQL/replacement-process recovery tests pass. The
official RADAR image also passed an actual Swarm task replacement with retained
input: two replayed readings were rejected without count/evidence advancement,
then fresh input advanced both. A further old/new writer overlap probe reproduced
a checkpoint overwrite race; ownership fencing is being completed separately.

Step 8 follow-up: Revalidation after unlocked workload retirement also recomputes
affected monitors, rejecting a newly admitted monitor even when catalogue and
collection revisions did not change. Both concurrent catalogue-save and new
pending-monitor cases pass against actual PostgreSQL and Swarm.
