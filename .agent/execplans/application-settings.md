# Separate preferences from system diagnostics

## Goal and context

Give Settings a focused preferences dialog inspired by a category-based desktop
settings layout. Move the existing collection and storage diagnostics to a
dedicated System status page. Keep Account and catalogue configuration in their
existing places. This task does not change primary workspace navigation.

The current Settings page is entirely read-only operational information.
`AppHeader` exposes a separate theme dropdown and `ApplicationMenu` links to
`/account/settings`. The existing theme provider already persists Light, Dark,
and System preferences and follows operating-system changes. Reuse that contract;
no backend configuration or schema changes are needed. `.agent/PLANS.md` is absent
in this checkout, so this file records the plan directly.

## Design

- Move the diagnostic page to `/system/status`, titled System status, with its
  existing health polling, storage refresh, retention information and permissions.
  Redirect the former `/account/settings` diagnostic URL to that page.
- Offer Account, Settings, System status and Logout in the shared application menu.
  Settings opens a modal over the active workspace without navigating, preserving
  unsaved input, selection and scroll. Restore focus to the menu trigger on close.
- Use a two-pane responsive dialog with Appearance as the first real category.
  Present native radio choices with theme previews for Light, Dark and Follow
  system. Apply and persist changes immediately using the existing theme provider.
  Remove the header theme dropdown and its unused component.
- Include accessible names, keyboard operation, focus trapping, reduced-motion
  compatibility, semantic colours and layouts down to 320px.
- Update affected test journeys and user/developer/operator documentation.

## Progress

- [x] Inspect current routes, shared menu/header, preferences and diagnostics.
- [x] Implement the settings dialog, appearance controls and System status route.
- [x] Update focused tests, existing theme journeys and documentation.
- [x] Run lint, production build and affected integration tests.
- [x] Rebuild the isolated Docker frontend and validate against the real API in
      desktop/mobile browsers, including theme persistence and status polling.
- [x] Inspect screenshots and final diff; record results.

## Validation

Use bundled Node 24 and locked dependencies. Use a workspace-local temporary
directory for Vitest and host access when required by the Windows sandbox.
The isolated `off-key-settings` Compose stack at `http://127.0.0.1:5174` is running
the current backend and is the end-to-end target. Preserve other stacks and data.
Check native radio keyboard operation, live system-theme changes, persistence
after reload, menu/dialog focus, unchanged underlying workspace input and URL,
real health/storage responses and automatic polling. Exercise both themes and
small portrait/landscape viewports without horizontal overflow.

## Results and refinements

All 93 affected tests pass across ApplicationMenu, ApplicationRouting, AppRoutes,
SystemStatus, CollectionHealth, ThemeProvider, ExplorerWorkspace and
SourcesWorkspace. The moved storage tests now accept locale-correct decimal
separators. The existing monitoring navigation test gives its first lazy module
import a five-second wait (matching other lazy-preview waits), because a cold
Windows transform exceeds Testing Library's default one second. All functional
assertions remain intact; no production timing or behavior was changed for this.

Lint and the production build pass. The existing large telemetry-chunk advisory
remains. The isolated Docker frontend was rebuilt successfully; its backend and
other deployment data were preserved.

Eight Chrome journeys pass. Five use the real Docker backend and exercise
appearance persistence/reload, operating-system changes, explicit overrides,
native radio keyboard navigation, focus trapping/restoration, outside click and
Escape dismissal, preserved workspace input/DOM/URL, real status polling and
storage refresh, old-link redirection, and existing catalogue import/export and
editing. Three existing chart journeys additionally verify header alignment,
responsive charts and retained detector/zoom state through appearance changes.

Desktop light/dark and mobile/landscape screenshots were visually inspected.
The native radio covers the whole theme card so browser focus and scrolling
keep the entire selected control visible on a 320px screen. The close control
stays outside the scrolling pane. Screenshots are saved in the chat's
visualization directory as `application-settings-dark.png`,
`application-settings-light.png` and `application-settings-mobile.png`.

The preview remains available at `http://127.0.0.1:5174`.
