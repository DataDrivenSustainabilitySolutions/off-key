# Code quality review

Reviewed commit: `a5a9a90`. Date: 2026-09-08.

**Verdict: substantial simplification is warranted. Fix persistence ownership and runtime-state inconsistencies before undertaking a broad refactor.**

The project is in development. Historical API, checkpoint, and database compatibility are not requirements for the proposed design. This does not imply permission to erase existing databases or disable current integrity constraints.

The findings below describe the original audit. Remediation progress is recorded at the end of this report.

## Scope and evidence

Repository-wide inventory covered 299 tracked Python/TypeScript/TSX files, totaling 52,939 lines including tests. Structural inspection parsed all 142 production Python modules. Detailed tracing focused on service orchestration, MQTT ingestion/persistence, detector state and checkpoints, configuration, database ownership, gateway/data-service boundaries, and frontend monitoring/chart data flows. CI and development tooling were also inspected. This was a risk-based codebase review, not an exhaustive proof of every execution path.

| Check | Result |
| --- | --- |
| Backend suite, `cd backend && .venv/bin/python -m pytest -q` | 534 passed, 1 skipped; 8 warnings |
| Frontend suite, `cd frontend && npm test -- --reporter=dot` | 173 passed across 22 files |
| Frontend lint and production build | Passed; build warns about the roughly 695 kB Details chunk |
| `backend/.venv/bin/ruff check .` | 5 existing findings with local Ruff 0.16.4 |
| `backend/.venv/bin/ruff format --check backend dev` | 198 files already formatted |
| Isolated fault-injection / state reproductions | Confirmed batch-loss boundary, cumulative circuit-breaker errors, unbounded proxy batch ownership |

No Docker workloads, external services, or databases were modified. Browser E2E and live TimescaleDB migration/integration checks were not run. Passing mocked/unit tests does not validate fresh-schema bootstrap, live overload behavior, or browser request races. Local Ruff is newer than the pre-commit pin (0.14.0), so these five findings are not evidence that the pinned CI lint job fails.

## Findings

### 1. [P2] Delete historical schema normalization from normal startup

**Location:** [DB Sync initialization](backend/services/db/sync/src/off_key_db_sync/service.py#L42), [legacy anomaly migration](backend/services/db/sync/src/off_key_db_sync/service.py#L507), [canonical models](backend/libs/core/src/off_key_core/db/models.py).

`SyncService` is 1,169 lines. Initialization runs eight migration methods before `Base.metadata.create_all`. It checks historical columns and constraints, rewrites/backfills rows, normalizes model families, and reinstalls database behavior during ordinary startup. `_migrate_anomaly_identity` alone spans 242 lines. This makes the normal boot path depend on a history of schemas that the project no longer needs to support.

**Simplification:** establish one supported development schema and one idempotent bootstrap path. Remove historical column/PK conversion and legacy value backfills from normal startup. Put current table declarations and required trigger/index/TimescaleDB setup in one canonical schema boundary. Preserve current anomaly identity synchronization, retention policies, and evidence constraints; they are active behavior, not obsolete compatibility.

**Validation before implementation:** bootstrap an empty disposable TimescaleDB database, bootstrap it again, then exercise anomaly insert/identity lookup/delete and evidence writes for both strategies. Reject an unsupported old schema explicitly; do not silently drop data. Splitting the same migration history into multiple files would improve navigation but miss the larger opportunity to delete it.

### 2. [P1] RADAR relinquishes batch ownership before entering its recovery boundary

**Location:** [batch flush](backend/services/mqtt/radar/src/off_key_mqtt_radar/database.py#L757), [writer loop](backend/services/mqtt/radar/src/off_key_mqtt_radar/database.py#L432), [result contract](backend/services/mqtt/radar/src/off_key_mqtt_radar/models.py#L93).

`_flush_batch` removes the snapshot from `write_queue`, then initializes the session factory, selects persistence candidates, and builds evidence records **before** its `try`. An exception during preparation bypasses requeue/retry and error accounting. When invoked by `_writer_loop`, it reaches the outer exception handler and the background loop exits.

**Reproduced:** queued one result and injected `ValueError` from `_build_evidence_records`. After `_flush_batch` raised, the queue contained zero records and `total_errors` remained zero. This demonstrates the exception boundary defect; it does not claim that a specific live detector currently emits malformed evidence.

The 1,079-line module also reconstructs strategy, phase, value type, alignment, and tracker shapes from `dict[str, Any]`. Similar strategy/phase checks appear in `RadarService._handle_mqtt_message`. That loose contract is exactly where preparation can fail and where new strategies force more branches into the writer.

**Simplification:** give one flush operation ownership of the snapshot through preparation, persistence, and recovery. Separate deterministic result-to-record projection from queue/session orchestration. Define explicit static/adaptive result payloads and one persistence eligibility rule; eliminate obsolete tail-probability compatibility inference once current producers use the contract.

**Validation before implementation:** preparation failure, session-factory failure, cancellation, failed retry, and a malformed result mixed with valid results. Verify that valid records survive and the writer continues. Specify a rejected-record policy so one permanently invalid result cannot cause endless retries.

### 3. [P1] Proxy persistence bypasses the ingestion queue's capacity limit

**Location:** [batch handoff](backend/services/mqtt/proxy/src/off_key_mqtt_proxy/telemetry.py#L225), [failed-batch retention](backend/services/mqtt/proxy/src/off_key_mqtt_proxy/telemetry.py#L397), [bounded MQTT handler queue](backend/services/mqtt/proxy/src/off_key_mqtt_proxy/client/messaging.py#L215).

Every batch handoff creates another task, retains the batch in `processing_batches`, and immediately returns. Nothing bounds the number of database batch tasks. Exhausted batches are appended to `failed_batches` without a size limit, replay, or eviction. The bounded MQTT queue cannot enforce downstream backpressure because enqueueing into the writer returns before persistence completes.

**Reproduced:** with persistence stalled, 50 handoffs produced 50 retained batches and 50 background tasks. With retries exhausted, 50 failed batches remained retained. No real database was used; the concern is the unbounded ownership model, not a measured production memory-growth rate.

**Simplification:** use a bounded batch queue with a fixed worker count. A worker owns a batch through its retry lifecycle. Choose explicit backpressure and failed-record handling; a persistent failure store is appropriate if retry across process restarts is required. Do not replace the unbounded failed list with silent eviction if data preservation is intended.

**Validation before implementation:** sustained arrivals during a blocked database, bounded in-flight work, producer backpressure, retry exhaustion, and shutdown while workers are blocked. Preserve the current charger/telemetry transaction.

### 4. [P2] Hot reload publishes configuration that running components do not use

**Location:** [reload application](backend/services/mqtt/radar/src/off_key_mqtt_radar/config_watcher.py#L253), [change handling](backend/services/mqtt/radar/src/off_key_mqtt_radar/config_watcher.py#L302), [component construction](backend/services/mqtt/radar/src/off_key_mqtt_radar/service.py#L114).

`reload_config` mutates environment variables and clears settings caches, then replaces `service.config`. Existing MQTT and database components retain their original config object; the detector has its separately constructed config. Connection and subscription changes only log messages. Only the memory limit is applied to a live component. Reload still records success.

For example, a topic change can make the service's advertised configuration disagree with MQTT subscriptions and the existing required-sensor cache. A model/strategy change does not rebuild the detector. Failure does not roll back the environment/caches. This is partial application presented as successful reconfiguration.

**Simplification:** remove hot reload and require restarting the workload for config changes. In this development-stage project, that is much simpler than implementing atomic replacement of MQTT, detector, alignment, persistence, and health state. If hot reload is actually required, define a small explicit set of reloadable fields and reject unsupported changes before publishing them.

**Validation before implementation:** verify changed broker/topics/model settings either remain unapplied with a clear restart requirement or take effect consistently after a full restart. No partially updated success state should be possible.

### 5. [P2] The circuit breaker's error window never forgets successful traffic

**Location:** [error accounting](backend/services/mqtt/radar/src/off_key_mqtt_radar/resilience.py#L163), [success accounting](backend/services/mqtt/radar/src/off_key_mqtt_radar/resilience.py#L170).

`last_errors` stores only failures. Its timestamps are never used to expire entries; successes do not advance a sample window, and closing the breaker does not clear the history. The reported `recent_error_rate` is the number of retained failures divided by 100, not a recent error rate.

**Reproduced:** 11 isolated errors, each preceded by 1,000 successful calls, opened the breaker after 11,011 attempts and reported an error rate of 0.11. The default fallback produces no alarms, so incorrectly opening the breaker suppresses normal detection for the configured timeout. Subsequent isolated failures can reopen it using the same stale history.

**Simplification:** choose a real policy: consecutive failures, the last N attempts, or an explicitly time-bounded error rate. Represent that policy directly with one bounded state structure. Keep timeout recovery and health reporting derived from the same state.

**Validation before implementation:** widely separated errors, a burst of failures, successful recovery, and failures after recovery. The existing repeated-error test does not cover these distinctions.

### 6. [P2] Monitoring requests can publish stale data across charger navigation

**Location:** [monitoring loaders and polling](frontend/src/pages/Monitoring.tsx#L99), [existing guarded refresh pattern](frontend/src/pages/Details.tsx#L127).

Monitoring's loaders update component state after every completion. Effect cleanup clears timers but does not cancel requests or reject stale results. Navigating from charger A to B while A's sensor/anomaly requests are pending allows a late A response to overwrite B's state. Polling can also overlap with previous requests or an explicit refresh and publish results out of order.

`Details` already uses an abort controller, cancellation flag, and in-flight guard. Monitoring independently implements a weaker lifecycle. This is a concrete inconsistency in ownership of asynchronous page state, not a request to introduce a generic fetching framework.

**Simplification:** give each charger-bound load generation one cancellation scope and guard all state commits. Use a single polling lifecycle with explicit non-overlap. Extract a small reusable controller only if it reduces both pages' ownership logic.

**Validation before implementation:** delay A responses, navigate to B, resolve B then A, and verify B stays visible. Also cover a slow poll overlapping a delete-triggered refresh and unmount cancellation.

## Recommended order

1. Add the missing failure-path regressions and repair RADAR snapshot ownership and proxy capacity limits.
2. Correct the circuit-breaker policy; remove misleading hot reload or limit it explicitly.
3. Establish the current-schema bootstrap and remove legacy migration/fallback machinery with disposable-database verification.
4. Introduce the explicit detector/persistence contract; eliminate duplicate strategy inference and table declarations where the canonical schema can be reused.
5. Consolidate Monitoring's request lifecycle and verify navigation races.

Avoid mixing detector mathematics, checkpoint semantics, schema deletion, queue ownership, and UI lifecycle changes in one patch. Backward compatibility is not a blocker; independently verifiable changes are still the safer way to preserve current behavior.

## Lower-priority tooling observations

Local Ruff reports three `UP042` enum findings, one `RUF036` union-order finding, and one `ASYNC240` path-I/O finding. Do not blindly apply the enum suggestions as cosmetic fixes: switching to `StrEnum` changes string-conversion behavior. Align the local/toolchain version with the pre-commit pin before turning this into a cleanup task.

The two production files above 1,000 lines already exceed the threshold at the reviewed commit; this review did not identify a new diff crossing it. The chart model (859 lines), proxy writer (778), and proxy service (772) are other sizeable modules, but line count alone is not a reason to split them without improving ownership or deleting complexity.

## Remediation log

### Finding 1 — current-schema bootstrap

Plan: delete historical upgrade paths, validate existing table shapes before DDL,
and retain current schema integrity behavior in the core database layer.
Implemented: canonical bootstrap and identity trigger; obsolete shapes fail without
rewriting data. `SyncService` shrank from 1,169 to 234 lines. Added disposable
TimescaleDB integration coverage for repeated bootstrap, both evidence strategies,
identity creation/cascade deletion, and obsolete-schema rejection.
Validation: backend main test directory passes (444 passed, 2 skipped); focused
bootstrap tests and changed-file Ruff checks pass. All 9 focused tests pass against
a disposable TimescaleDB instance, including repeat bootstrap and integrity checks.
