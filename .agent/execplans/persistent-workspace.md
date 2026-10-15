# Persistent catalogue and top-level workspace navigation

## Objective

Keep one MQTT catalogue sidebar mounted while Monitoring, Sources and Reporting
change the main content through the always-visible navbar. Preserve catalogue
hierarchy, search, browse location, selection, scroll and width across section
changes; keep real catalogue and activity updates working. Selecting a source
scopes the active section to its monitoring services, configuration or reports.

The current route tree mounts separate Monitoring and Sources shells; Sources
also drops entities from its index. Reporting has no catalogue. Each workspace
owns another catalogue fetch, telemetry instance and settings dialog. This is a
shared-layout refactor. `.agent/PLANS.md` is absent, so this file records the plan.

## Design

- Put all protected routes beneath one application layout. It owns the header,
  persistent sidebar, responsive drawer and catalogue dialogs. Wrap the routed
  content in its own Suspense boundary to keep the shell present during lazy loads.
- Add an account-scoped catalogue context with one `useSystemDocument`, one
  navigation index (brokers, entities, topics and readings), one live preview
  instance and shared history cache. Reuse existing navigation preferences and
  revision checks. Runtime polling must not rebuild the catalogue index.
- Keep primary navigation exclusively in the navbar, visible on small screens.
  A shared `source` URL parameter identifies the catalogue node across sections;
  legacy broker/topic/reading/entity links continue to resolve. Preserve browser
  back/forward semantics and service setup return links. Browsing branches remains
  separate from selecting the source for main content.
- Monitoring scopes services to selected reading IDs and retains service setup,
  detail, favourites and reading previews. Source/entity inspection remains
  available explicitly. Sources reuses its recording inspector for broker/topic/
  reading rules; entity configuration shows entity details and its readings,
  without applying broker-wide recording changes to an entity by mistake.
- Reporting filters by the catalogue's stable runtime entity/reading bindings,
  including multivariate sensor sets, and exposes a clear all-sources action.
- Preserve unsaved recording guards for both section and source changes. Prevent
  structural catalogue edits while a recording draft is dirty. Keep permissions,
  manual live-preview start/stop, account isolation and settings focus behavior.
- Move service favourites out of the MQTT sidebar; retain their existing filter
  and actions in Monitoring. Keep reading favourites as source shortcuts.

## Progress

- [x] Inspect current shells, navigation indexes, recording rules and reporting.
- [x] Implement shared catalogue state, URL helpers and persistent app shell.
- [x] Convert Monitoring/Sources to content-only views and scope Reporting.
- [x] Update behaviour tests, browser journeys and navigation documentation.
- [x] Run affected tests, lint and a production build; resolve regressions.
- [x] Validate real Docker/API/MQTT behavior and desktop/mobile screenshots.
- [x] Review final changes and record evidence and remaining limits.

## Validation strategy

Use the current isolated `off-key-settings` stack and its real API/MQTT data.
Browser checks must retain actual sidebar/list DOM handles, verify unchanged
scroll/search/selection across all three sections, count catalogue GETs, exercise
history and dirty-draft cancellation, and confirm actual scoped service/report
data. Existing source recording, catalogue settings, application settings and
chart flows must remain functional. Check 320px mobile navigation and drawer
focus, desktop sidebar resizing/collapse and both themes. Use bundled Node 24 and
workspace-local temporary files; use host permissions when required for Docker
and Windows test/module access. Preserve all prior uncommitted work.

## Results

The shared layout owns the complete catalogue lifecycle. Monitoring and Sources
are content-only views; Reporting uses the same selected source. There is no
second source-specific navigation index. The app frame has its own lazy boundary
after sign-in, while routed main content has loading/error boundaries that keep
the catalogue available. The production entry JavaScript is approximately 396kB,
compared with 416kB before the refactor; the existing telemetry chunk advisory
remains unchanged.

All 600 frontend tests pass across 52 files. Routing and inspector behaviour tests
load their real lazy modules during setup so their assertions do not time the
initial module transform. Existing service-detail and service-setup waits remain;
functional and timing-state assertions are intact. The final unit run uses one
worker, separately from browser workloads, to avoid Windows resource contention.
Lint, the production build, strict Zensical documentation build and
`git diff --check` pass.

All 26 browser journeys pass: eleven against the real Docker backend,
plus fifteen existing chart regression journeys using their established fixtures.
The new navigation journey retains actual sidebar/list DOM handles and verifies
search, selection, scroll, keyboard-adjusted width, browser history, dirty-draft
Stay/Discard choices and no extra catalogue reads across all three sections.
It starts one real live-preview lease, publishes a value through MQTT, verifies
the same connection/value across section changes and mobile, and releases it
only on explicit Disconnect. Real recorded data and API-persisted reports verify
entity/reading filtering and the entity's per-reading Sources configuration.
Anomaly fixture creation uses the published OpenAPI `payload` envelope.

The complete real monitoring journey records an opted-in reading, restores mobile
history, preserves service-setup input across a Sources detour, launches a real
RADAR worker, renames/stars its service, switches through all three sections with
the same catalogue, receives adaptive evidence and removes the worker. The test
caught a duplicate Sources action during setup; the header now leaves setup and
service-detail actions to their existing content controls.

Catalogue settings, appearance preferences, status polling, imports/exports,
structural editing and chart state remain verified. Both themes and the 320px
mobile layout were visually inspected. Screenshots are saved in the chat's
visualization directory as `shared-workspace-dark.png`, `shared-workspace-light.png`,
`shared-workspace-mobile.png` and `shared-monitoring-evidence.png`.

The expanded chart suite exposed an assertion against an intentionally unrendered
offscreen chart. Its linked-navigation journey now scrolls each chart into view
before checking the presence or absence of inspection controls; it retains all
linked/independent navigation assertions and passes with the full browser suite.

Temporary catalogue fixtures, report records, preview leases and the monitoring
worker are cleaned up by their real APIs. The isolated frontend remains running
at `http://127.0.0.1:5174`; other deployment state and prior uncommitted work are
preserved. No new dependencies or backend contracts were required.

## Follow-up: collection navigation and root action

Replace the repeated Catalogue/Catalogue groups/Saved system navigation with a
Collections dropdown, the existing small context count and a FolderRoot button
labelled Back to catalogue. Hide the stored catalogue name at the root; retain
branch names and their ancestor menu. Keep existing saved groups and their
membership counts, and use Collection consistently in settings and the editor.
The explicit root action clears search and main selection and starts the broker
list at the top, including when already at the root. Ordinary navigation retains
its existing scroll restoration. No database or export schema changes are needed.

Validation uses the existing behaviour suites and the real isolated Docker
application. A new browser journey creates 31 brokers and a collection, saves a
collection through the actual editor, returns from collection/branch/search views,
checks root scrolling and keyboard operation, and captures desktop themes and a
320px mobile drawer. Temporary IDs are removed by the API after the journey.

The follow-up passes all 600 frontend tests and nine real browser journeys for
settings, catalogue editing, collections, persistent navigation and monitoring.
The import regression now checks the saved catalogue name in Catalogue settings,
where it remains available, rather than expecting the removed sidebar heading.
Lint, the production build and strict documentation build also pass. Desktop
light/dark and mobile screenshots were visually inspected; the root control keeps
a 44-pixel touch target on mobile. The fixtures and monitoring workload are cleaned
up after validation. Screenshots are saved as `catalogue-collections-light.png`,
`catalogue-collections-dark.png` and `catalogue-collections-mobile.png` in the chat's
visualization directory.
