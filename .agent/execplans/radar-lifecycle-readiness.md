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

## Targeted production-validation improvements

The user approved implementing the four review recommendations on 2026-10-16.
Keep each change independently reviewable and validate it before proceeding.
PR #306 at `f1f4624` passed all 20 checks, including 102 RADAR integration tests,
31 browser journeys and both monitoring/backup/restore/redeployment checks.

1. [x] Replace running-only revival coverage with one real pending-to-running
   Swarm transition. Assert the inactive row and its operational evidence remain
   unchanged while scheduling is blocked, then verify revival after scheduling.
   Prove the regression rejects a deliberately broadened readiness condition in
   the disposable runner, restoring runtime source afterward.
2. [x] Require nonempty JUnit results with zero skips in the dedicated RADAR job.
   Exercise acceptance with real integration results and rejection with actual
   pytest skip/collection-only results. Keep the general backend suite's optional
   integration skips intact; avoid fixed expected test counts or new dependencies.
3. [x] Set Playwright's CI flaky-test policy to fail while retaining the existing
   diagnostic retry. Demonstrate the policy with an isolated retry-only test using
   the real runner, then run the existing production browser journeys in CI.
4. [x] Add `RADAR production integration`, bound to GitHub Actions, to main's
   required checks. Save the prior state and verify every existing required check,
   app binding and strictness setting survives the update.

Commit the three repository changes separately, push once to PR #306 and wait for
the final revision's complete required checks. Record final live CI evidence on
the PR, clean up only fixtures created for this work, and preserve production
deployment as a separate post-merge verification.

Step 1: the replacement passes against real PostgreSQL/Swarm on Linux Python
3.14.8 (11.02 seconds). With only the readiness condition broadened to accept
pending tasks, the old running-only test still passes (7.85 seconds) and the
replacement fails at `assert current.status is False` (7.34 seconds). Both runtime
and test source are restored in the disposable runner. The complete affected
lifecycle/reconciliation suites then pass: 32 tests, zero skips, in 113.82 seconds.
Applicable repository hooks pass.

Step 2: the dedicated workflow now emits JUnit and accepts only a nonempty report
without skipped cases. The exact inline guard accepts the real 32-test report and
rejects both an actual skipped integration invocation and a collection-only
invocation, even though those pytest processes exit successfully. YAML and all
applicable hooks pass. No new dependency or fixed expected test count is used.

Step 3: Playwright's existing CI configuration now sets `failOnFlakyTests` while
retaining one retry. An isolated real-runner case that fails first and passes on
retry exits zero before the change and one afterward, classified as flaky in both
runs. A clean case still exits zero. These policy probes use no application data,
auth state or browser session; the final native smoke job remains responsible for
the real production browser journeys.

Step 4: main's required-status-check policy now includes `RADAR production
integration` bound to the verified `github-actions` app (15368). Read-back
verification confirms the nine prior required checks and their exact app bindings
are preserved, strict/up-to-date enforcement remains enabled, and RADAR is the sole
added requirement. Before/after policy snapshots are retained in the local review
cache. The change uses the specific required-status-check endpoint.

The two labeled containers and dedicated network for targeted validation have
been removed after ownership checks; no owned Swarm workloads remain. The isolated
Playwright policy probe and its artifacts are preserved under the review cache.
All four targeted implementation steps are complete. Final revision CI, including
the new zero-skip guard and strict browser policy, is recorded on PR #306.
