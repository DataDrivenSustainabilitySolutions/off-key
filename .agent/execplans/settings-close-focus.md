# Preserve newer focus when Settings closes

## Problem and evidence

Main `c3f75cd` passes RADAR production integration but fails Deployment Smoke
because the branding keyboard journey loses focus after closing Settings. The
first attempt fails at `branding.spec.ts:22`; the retry passes. The strict flaky
policy correctly blocks the release. The production workflow only completes
eligibility and skips deployment.

The trace places the home-link focus operation just after the settings dialog
disappears. Radix defers its unmount focus callback with a timer; ApplicationMenu
unconditionally focuses the menu trigger in that callback. Reproduce the race
before changing this behavior. Keep normal close/Escape focus restoration.

## Plan

- [x] Inspect main and PR results, failure trace and actual production eligibility.
- [x] Reproduce the deferred callback overwriting a newer focus choice using the
      real Radix dialog and a controlled timer.
- [x] Preserve a newer connected focus target and retain menu focus restoration
      when closing the dialog leaves focus on the document body.
- [ ] Validate real browser keyboard navigation against the actual local API,
      alongside the affected frontend tests, lint and production build.
- [ ] Review the patch and publish a focused corrective PR with native smoke CI.

Do not relax assertions, extend waits, disable the flaky policy, rerun main to
obtain a lucky pass, or recreate the removed monitoring automation. Preserve the
existing local development stacks and data.

## Validation results

The real Radix component regression fails before the change: deferred cleanup
focuses Application menu after the home link is focused. The same sequence also
fails in real Chrome against the local API, with focus events recorded as
`Close settings -> Aberration home -> Application menu`. No API responses or UI
components are mocked in the browser probe. The trace's exact timing is exercised
by focusing home when the real dialog is removed, then awaiting its real unmount
callback. The implementation now restores the menu only if focus is on the body.

The isolated checkout uses main's unchanged lockfile. All 612 frontend tests pass
on Node 24.19.0, including normal close, Escape restoration and the deterministic
race. ESLint, TypeScript and the production build pass. On Windows the full test
run needs a workspace-local temporary directory shared by the workers; no test
timeouts or application timing are changed. The native smoke job must still
verify the complete release rehearsal on the corrective PR.
