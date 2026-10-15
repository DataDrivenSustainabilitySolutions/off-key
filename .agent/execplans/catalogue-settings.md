# Catalogue settings redesign

## Goal

Replace the raw catalogue settings dialog with a coherent, accessible settings
surface using the application's existing colours, typography and controls. Keep
the real catalogue editing, export and reviewed replacement workflows intact in
both Sources and Monitoring. The application continues to use one shared catalogue.

## Context

The shared body is `frontend/src/features/explorer/ExplorerSettings.tsx`.
`SourcesWorkspace.tsx` and `ExplorerWorkspace.tsx` each own a Radix modal shell.
The existing settings CSS lives among explorer navigation and editor styles in
`explorer.css`. No `.agent/PLANS.md` exists in this checkout, so this plan records
the implementation and validation steps directly.

## Design and boundaries

- Add a shared dialog heading and scoped stylesheet for settings only. Other
  explorer dialogs and structure editors retain their existing layout.
- Present the current catalogue with actual counts, four labelled creation
  actions with short explanations, and the existing entity chooser where enabled.
- Give export and import their own labelled rows. Preserve file validation,
  captured revision checks, explicit replacement, concurrent-action locking,
  and error handling. Show the reviewed filename and catalogue counts.
- Use semantic theme variables, visible keyboard focus, accessible labels,
  comfortable touch targets and a layout that works at 320 pixels.
- Make read-only and busy states clear without changing backend contracts,
  catalogue contents or collection behaviour.

## Progress

- [x] Inspect the supplied image, both entry points, styles and existing tests.
- [x] Implement the shared heading, settings layout and scoped styles.
- [x] Update focused behaviour tests and relevant user documentation.
- [x] Run lint, production build and affected unit/integration tests.
- [x] Exercise the actual application in a browser at desktop/mobile sizes and
      in both themes; validate file review and real persistence when available.
- [x] Review the final diff and record results and remaining limitations.

## Validation

Use the bundled Node 24 runtime and the existing locked frontend dependencies.
Keep temporary test files under ignored workspace directories because the
Windows sandbox's default temp directory previously caused permission errors.
Run `ExplorerSettings`, `SourcesWorkspace` and relevant `ExplorerWorkspace`
tests. Check the existing stale/lazy-loading timeout separately if it recurs;
do not hide a regression by changing expectations. Use the real Compose
application as the end-to-end target and preserve existing catalogue data.

## Decisions and results

Docker is available after starting Desktop and using the host permission required
for its named pipe. The running `off-key` stack exposes an older API without
catalogue or member endpoints. The isolated `off-key-settings` stack was built
with `dev/local/run.py`, using separate ports, secrets and volumes. Its production
frontend is available at `http://127.0.0.1:5174`.

The production build, lint and all 48 affected tests pass. Running those tests
with host filesystem access resolves the Windows sandbox's repeated module-loading
timeouts without changes to test timeouts or application behaviour. The 12 settings
tests cover file validation, revision pinning, permission loss, cancellation,
concurrent operations and errors.

The normal invitation/login setup and both new real browser journeys passed.
They verify a real export and cancelled import, broker/entity persistence and
entity editing, keyboard focus restoration, light/dark themes, and the Sources
and Monitoring entry points at 320 pixels. The temporary broker and entity are
removed afterward through the API. Desktop and mobile screenshots were inspected
and saved in the chat's visualization directory. Existing deployment data is intact.

Sources now restores focus to the settings opener, falling back to the sidebar
toggle when a mobile drawer opener has unmounted. Settings styles are scoped to
the shared settings surface; structure editors keep their existing layout.
