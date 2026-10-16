# RADAR lifecycle readiness and reconciliation regression

## Objective

Investigate the lifecycle failure on main `cea69f9`, resolve its confirmed cause,
and open a focused follow-up PR. Reduce timing assumptions and test coupling while
preserving real PostgreSQL/Swarm coverage of concurrent heartbeats and lifecycle
generation fencing. `.agent/PLANS.md` is absent; this file records the plan directly.

## Evidence and working hypothesis

The final PR integration run passed all 98 tests. Its actual tested merge commit
and main have the same source tree. The main integration run passed 97 tests and
failed `test_reconciliation_docker_latency_does_not_block_or_overwrite_heartbeat`
at `assert current.status`. The failure does not record the Docker observation.

The test clears `status` after workload creation, then expects reconciliation to
revive it while also preserving a newer heartbeat. Creation checks for early task
failure but does not require a running task. Revival requires a running Docker
observation; preserving a heartbeat must also work before a task is running.
This is a confirmed test precondition gap, but the historical failure's exact
Docker state cannot be recovered from the available log.

## Sequence

- [x] Check current main, local instructions, clean checkout and existing fixtures.
- [x] Create branch `codex/radar-lifecycle-readiness` from current main.
- [x] Reproduce the failing assertion with real PostgreSQL and an unscheduled Swarm
  task, recording its actual state. Keep the original test unmodified for this check.
- [x] Separate heartbeat preservation, revival and generation fencing contracts.
  Coordinate observations explicitly and ensure background tasks are awaited on
  failure. Use real readiness predicates where the contract requires running.
- [x] Simplify construction or shared test support only where it removes existing
  brittle initialization or repeated synchronization code.
- [x] Run the focused real regressions, complete backend suite and repository hooks.
- [x] Review the final patch and document reproduction and regression evidence.
- [x] Clean up only fixtures owned by this investigation.

Publication: commit the reviewed patch and open/attach a corrective PR. Require
the native Linux production integration and deployment-smoke checks to pass;
their live results and final validation summary are recorded on the PR.

## Design constraints

Do not extend startup grace periods or add production retries solely to make a test
pass. Preserve asynchronous workload creation and durable running intent through
Swarm scheduling. Use bounded waits on observable conditions, not fixed sleeps for
readiness. Preserve both heartbeat payload/timestamp and newer stop generation.
Capture fixture diagnostics before teardown removes the real workload. Leave the
existing local deployments and Swarm manager intact.

Production deployment remains subject to its normal checks.

## Validation and results

2026-10-16: The unmodified original test fails at the same `assert current.status`
against Python 3.14, the pinned production TimescaleDB image and an actual Swarm
task held pending by an unsatisfiable placement constraint. An observation wrapper
records `REAL_SWARM_OBSERVATION=pending`; it forwards the real Docker operation.
The single-test reproducer failed in 7.45 seconds. This confirms the failure
mechanism without claiming the historical runner's missing Docker state is known.

Implementation separates heartbeat preservation across real pending/running/failed
tasks from readiness-dependent revival and a newer stop generation. The stop test
starts with `status=False`, so applying its captured running observation would
actually revive the row if generation fencing failed. Both concurrent-write tests
pause after a real observation and always release/await reconciliation in cleanup.
Explicit dependency injection replaces constructor bypasses in the affected tests.

All final validation must use real integrations; boundary mocks may supplement
unit coverage but cannot establish the production result.

The 21 focused checks pass on Linux Python 3.14, including five real PostgreSQL/
Swarm concurrency/readiness cases. Controlled mutations in the disposable runner
prove the new stop-generation test fails when snapshot generation matching is
removed (7.19 seconds), and the failed-task heartbeat case fails when the newer
heartbeat check is removed (7.73 seconds). The source is restored after each
mutation sequence; no mutated production code enters the patch.

The complete backend suite passed on Linux Python 3.14: 1,068 passed, six eligibility
skips, in 237.37 seconds, using the real disposable database and Swarm manager.
All repository pre-commit hooks passed. The image-replacement scenario uses
published localhost ports and runs in its native Linux GitHub Actions production
integration job, together with all production integration tests. The other local
skips require the separate collection/deployment/Compose harnesses that CI runs.
Only the two labeled containers and one dedicated bridge created for this
investigation were removed; existing deployments and the Swarm manager remain.

## Deployment-smoke focus regression

PR #306's first head passed all 102 native Linux RADAR production integration
tests, including exact-image replacement. Deployment smoke instead failed the
existing mobile catalogue-root keyboard journey on both attempts. Its trace and
failure snapshot show Enter selecting a row and dismissing the drawer after the
test explicitly focused the root button.

ExplorerList restores branch focus after two animation frames without checking
whether another control has since received focus. A deterministic regression
using the real TanStack virtualizer reproduces the theft when toolbar focus moves
before either frame. Both cases fail before the change. Deferred restoration now
yields to a newer focus choice; the 19 list/sidebar tests pass, including the
existing saved-focus, viewport and selected-search-result coverage. The browser
journey and its expectations remain unchanged.

- [x] Reproduce the focus race before editing runtime behavior.
- [x] Preserve explicit focus with a small guard in the existing restoration path.
- [x] Complete frontend tests, lint, production build and repository hooks:
  611 tests across 52 files, ESLint, TypeScript/Vite and all applicable hooks pass.
- [x] Prepare the focus fix as a separate commit on the corrective PR, keeping
  the existing browser journey and its assertions intact.

After publication, verify the full native Linux deployment-smoke journey on the
updated PR revision. The PR's live checks and validation summary are the final
record of this result.

This PR smoke rehearsal is a disposable production-like deployment. It does not
establish that the main revision has reached the production environment; the
existing post-merge watch continues until an eligible main deployment is verified.
