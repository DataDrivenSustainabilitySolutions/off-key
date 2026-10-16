# Visual monitoring pipelines

## Objective and baseline

Implement the reviewed visual monitoring pipeline plan end to end for static and
adaptive monitoring, with one detector, branching feature processing, a shared
versioned design library, explicit replacement, existing decision policies and
bounded live inspection. OFF-KEY starts at main c3f75cd; Aberrant starts at
02e8147 (1.2.0), while OFF-KEY currently pins 1.1.0. `.agent/PLANS.md` is absent;
this file is the living execution plan following the existing repository convention.

## Non-negotiable contracts

- OFF-KEY Pydantic models are the sole persisted/public graph definition.
- Aberrant adds a standalone numeric GraphPipeline containing transformer DAG
  plus one terminal model. Existing linear Pipeline and DetectorConfig semantics
  remain intact. Readiness gates downstream learning; transactions cover terminal
  learning; uncertain model mutation is fatal rather than a fallback score.
- Static preprocessing fits training data only and freezes for calibration and
  inference. Batch centered PCA and online uncentered PCA have distinct identities.
- Input slots have stable IDs, distinct numeric reading bindings, exact optional
  units and one runtime entity. Presentation metadata is non-executable.
- Draft save, revision publication and activation are separate. Runs retain
  immutable bound snapshots independently of service/checkpoint deletion.
- Durable activations reserve the predecessor/successor input union. All starts,
  collection mutations, reconciliation and release paths use one claim authority.
- Preflight executes in the exact target runtime image before retirement. Remote
  uncertainty retains claims. A successor starts only after confirmed shutdown.
- Deployment preparation and nonterminal activations arbitrate under the shared
  collection lock; background transitions obey the same gate.
- Fatal state uncertainty crosses resilience/message boundaries, disables further
  calls and every checkpoint path, and preserves the last committed signed state.
- Diagnostics are actual execution observations: one coherent sampled envelope,
  bounded previews, detached snapshots, no extra inference or subscriptions.

## Implementation sequence and responsibilities

- [x] Recheck both source baselines, local instructions and current test gates.
- [x] Create OFF-KEY branch codex/visual-monitoring-pipelines.
- [x] Isolate the upstream Aberrant changes in an ignored local clone.
- [x] Gate 1: upstream composition, readiness, transactions, feature operations,
  observations, standalone tests/docs and compatible release preparation.
- [ ] Shared contracts/compiler/catalog/schema generation; persistence and APIs.
- [ ] Gate 2: real adaptive/static graph execution and a minimal end-to-end
  saved/bound/preflighted/replaced pipeline with actual diagnostics.
- [ ] Gate 3: durable claims, lifecycle cancellation/reconciliation, deployment
  arbitration, recovery/fatal shutdown and migration/rollback verification.
- [ ] Gate 4: shared library and complete React Flow editor, templates, bindings,
  inspector, keyboard/mobile navigation and coordinated live polling.
- [ ] Real MQTT/PostgreSQL/Swarm/browser verification, performance/bounds checks,
  full repository gates and independent final reviews.
- [ ] Publish compatible Aberrant dependency, lock/check OFF-KEY manifests and
  catalog, document rollout/rollback, and prepare reviewable upstream/OFF-KEY PRs.

## Validation

Final confidence must use real models and infrastructure. Unit tests cover graph
contracts, numerical reference calculations, single updates, readiness and rollback.
Integration tests cover MQTT, PostgreSQL migrations/persistence, Docker/Swarm
preflight/replacement/uncertain remote outcomes, source claims and release races.
Browser journeys cover graph authoring and live inspection using the real stack,
including existing workspace identity, Sources detours, mobile and keyboard flows.
Run existing backend/frontend lint/tests/build, generated-contract/catalog drift,
repository hooks, native Linux RADAR production integration with zero skips and
deployment smoke without flaky retries. Preserve existing deployments and clean
only explicitly owned disposable fixtures.

## Progress and evidence

2026-10-16: Both source revisions are unchanged from planning. OFF-KEY is clean.
The sandbox requires approved execution for Git metadata, Docker and WSL access;
branch creation succeeded through that mechanism. Work is divided across the
upstream numeric library, shared contracts/lifecycle and editor, with runtime and
cross-stack integration owned by the primary agent. No feature is declared complete
until all gates above have real verification evidence recorded here.

2026-10-16 implementation: Aberrant's additive GraphPipeline now supplies staged
readiness, shared-node learning, graph-wide transformer transactions through model
learning, permanent uncertain-state fencing, detached optional observations and
standalone feature operators. Its scoped numerical/compatibility checks report
336 passes and 22 subtests; the supported upstream CI matrix and release remain
pending. A symmetric PCA eigensolver avoids complex bases on degenerate streams.

OFF-KEY now has shared graph contracts and compilation, library/revision/run/
activation storage and APIs, a credential-free constructor preflight, static batch
and adaptive runtime adapters, sampled diagnostics, and the editor implementation.
The static adapter reuses the existing PyOD/nonconform/martingale execution and
fits preprocessing only on training observations. Fatal execution crosses resilience
and message handling and blocks both routine and shutdown checkpoint export.
These integrations are under verification and are not release-complete.

Existing static conformal tests passed (32 cases), and 14 queue/runtime settings
checks passed with host loopback access. Windows sandbox asyncio socketpair setup
hangs without network permission; rerunning these checks with approved loopback
access succeeds. Dedicated native Linux 3.14 tests use the disposable image
offkey-pipelines-integration:dev, isolated network offkey-pipelines-test-20261016,
and PostgreSQL container offkey-pipelines-db-20261016 (published port 45297).
Existing user stacks have not been modified. Real constructor tests found a
missing/default-null binding canonicalization issue; shared fingerprint handling
is being corrected. All rollout gates remain open pending integrated results.

2026-10-16 integration review: canonical binding defaults and input-slot ordering
are fixed and covered by numerical checks. Real MQTT/PostgreSQL tests verify a
signed graph checkpoint round trip, coherent previews, fatal terminal mutation,
supervisor shutdown and preservation of the last committed checkpoint. Fatal
workers quarantine until their durable failed-generation fence commits; database
outages retry without exporting damaged state. A host loss before that commit is
an unknown crash and follows existing authenticated-checkpoint recovery with a
possible coverage gap. This limit is documented rather than claiming an atomic
transaction across numeric memory and PostgreSQL.

The upstream Aberrant PR 94 was merged as 20fb1047cb5998333bd42d854768343f32f71eb5.
The supported Linux/Windows Python 3.10–3.12 CI matrix, standalone installation,
optional dependencies, documentation, typing, lint and serialization checks all
passed. Release v1.3.0 was published successfully to PyPI by workflow 38885539131.
OFF-KEY now pins aberrant[faiss]==1.3.0 and its lock has been refreshed. Production
image validation is in progress against this published artifact.

The real isolated Swarm journey passed preflight in the exact image, a healthy
successor, replacement only after old task shutdown, competing legacy admission,
retained predecessor history, cancellation before retirement, bounded failure of
an unschedulable preflight, and stop-versus-replacement arbitration (297.56 s,
zero skips). Twenty PostgreSQL release/collection/pipeline checks also passed.
Independent review then identified stale controller leases and fatal-heartbeat
status races; fencing and lock-order fixes require a final rerun before Gate 3.

The browser adaptive journey has passed against actual MQTT/PostgreSQL/Swarm.
Final production-bundle journeys add explicit revision replacement and static
background fitting with continuous input. Sixty-four-node interaction fixtures
have passed responsiveness checks; retained heap is measured after collection to
exclude temporary allocation noise. Runtime maximum fixtures retained one bounded
snapshot (39,840 bytes at 64 nodes/128 edges, 71,985 bytes at full intermediate
width), with negligible late storage growth over 2,000 observations each. CPU
instrumentation overhead is still under controlled measurement and is not passed.

All new authoring remains disabled by default. Existing graph runs, inspection,
stopping and release recovery remain available with authoring disabled. No claim
of release completion is made until the remaining full repository, production
integration, performance and deployment rehearsal gates pass.
