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
- [ ] 3. Persist signed checkpoints across task/node replacement; real restart test.
- [ ] 4. Make rate/overflow/restart coverage gaps explicit and remove unsuitable defaults.
- [ ] 5. Persist desired workload state before Docker mutation and recover interruption.
- [ ] 6. Degrade health when required input or successful inference stops progressing.
- [ ] 7. Require successful SUBACKs before readiness, including reconnects.
- [ ] 8. Move external workload inspection outside database locks/transactions.
- [ ] 9. Bound thread-to-loop ingestion and run detector work serially off the loop.
- [ ] 10. Validate observation age, regression, duplicates and cross-sensor skew.
- [ ] Reconcile runtime resource budgets, documentation and deployment contracts.
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
