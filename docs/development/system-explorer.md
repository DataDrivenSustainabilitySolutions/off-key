# Monitoring workspace

The monitoring workspace is the signed-in application home at `/`. Login and the Monitoring navigation item lead here. The shared application header starts with the Aberration mark linking to home, followed by the catalogue toggle and primary navigation. Development and production builds include this lazy-loaded home. The former `/explorer` and `/spatial-lab` routes and the 3D experiment have been removed.

All authenticated routes share one lazy-loaded `ApplicationWorkspace`. Its sticky navbar always shows Monitoring, Sources, and Reporting, with the current section marked; mobile uses a second header row so these links remain visible. The MQTT catalogue sidebar stays mounted across section changes. The right-hand menu contains Account, Settings, Status, and Logout. Settings opens an appearance dialog over the current workspace. Diagnostics live at `/system/status`; the former `/account/settings` link redirects there. Logout clears the session and returns to login immediately. Entity definitions are managed within Sources; old `/entities` links redirect there. Entity and monitor details retain their functional workflows; accepted detector topics use the generic `telemetry/<entity>/<reading>` contract.

## Navigation

The same hierarchy contains brokers, entities, MQTT topics and readings in every section. Select a row to change the main content; use its chevron or Right arrow to browse its children. Back/Left restores the previous list, scroll position and visible keyboard focus. The current heading opens an ancestor menu. Single-child MQTT paths fold into one row while preserving every original topic segment and the complete ancestry. Topics with both their own readings and subtopics show both. Several payload fields on one MQTT topic are separate reading leaves.

The `source` query parameter identifies the selected catalogue node across sections; legacy broker/topic/reading/entity links still resolve. Browser back/forward restores that selection. Switching sections preserves catalogue search, browse location, row selection, width and scroll without remounting the sidebar or rereading the document. Live runtime updates continue. **All sources** clears the main-content scope while retaining the sidebar position. The **Back to catalogue** icon clears the search and main-content scope and returns browsing to the root at scroll offset zero. Root navigation shows only the broker count, without repeating the stored catalogue name; branch headings retain their ancestor menus.

Individual topic and reading rows use neutral circles rendered at 12 pixels, centered in the existing 16-pixel icon slot. A filled circle means a current preview or background recording subscription received a fresh message within the last 30 seconds. A hollow circle means it is waiting for fresh data or is not listening, distinguished by its hover text and accessible description. Retained values, old stored history, disconnected brokers and receipts outside the current preview scope do not indicate activity. Recording activity comes from bounded ingress receipt timestamps before sampling, so long recording intervals do not hide incoming traffic. Simulated preview activity is labeled explicitly. Indicators observe the existing runtime and preview subscriptions without changing collection policies or opening subscriptions for catalogue browsing.

The **Online topics only** toggle beside **Back to catalogue** applies the same activity predicate to reading leaves and retains their ancestors. `onlineNavigationIndex` builds a view of the existing index; it does not mutate the document, selection or subscription scope. Search is limited after filtering, and collection rows, reading favourites and counts use the filtered view. The filter observes existing runtime/preview updates and ages receipts every second while enabled. The validated `onlineOnly` preference persists per account in this browser; filtered and full lists keep separate scroll positions. An inactive selected source remains selected in the main content. Empty filtered lists show **No active topics** and an underlined **Show all topics** button in the list area. It disables the activity filter without changing the current folder, query or source selection.

Search reaches closed branches by name, stable ID, MQTT path, payload field, or ancestor context. Cmd/Ctrl+K opens and focuses search even with the sidebar closed; ArrowDown enters results. Up/Down and Home/End move within lists. Selecting a search result retains the search and its scroll position. Initial deep links reveal the selected source's branch. The default Monitoring view is the service list, scoped to the selected source's exact accepted inputs. Reading selections also show their preview; other source metadata is available with **Inspect source**. Browsing branches does not change the selected main-content scope.

The mobile sidebar uses an accessible modal drawer, with focus containment, Escape/backdrop dismissal, and focus returned to its opening control. Reduced-motion preferences disable navigation transitions. Light and dark themes follow the existing application theme.

The desktop sidebar has a draggable right edge. Width ranges from 240 to 480 pixels, with at least 480 pixels left for the workspace; narrower desktop windows temporarily constrain the displayed width without replacing the saved preference. Double-click resets to 288 pixels. The focused separator supports Left/Right (16 pixels), Shift+Left/Right (64 pixels), and Home/End. Escape or a cancelled pointer restores the width before the drag. Width persists per account in this browser. Dragging updates one CSS layout variable per animation frame and commits preferences only when released. Mobile continues to use its fixed-width drawer.

## Monitoring services

The home lists actual services from `/v1/monitors/all?active_only=false`: saved name, monitored scope, detector, lifecycle stage, preparation progress, last reported update and processed inputs. It has search and state filters, with Attention shown when a service reports a failure, degradation or stale status. No anomaly-count dashboard or fabricated healthy state is shown. Empty deployments offer service creation without activating any collection automatically.

The overview uses one compact status request every 20 seconds while visible, refreshing every five seconds while a service is open, without per-service Docker probes or history subscriptions. List rows are virtualized. Explicit service inspection loads its settings; Evidence mounts only the selected reading’s chart. Preparation, read-only configuration, existing static/adaptive detector settings, dynamic score/threshold charts, and stop/remove actions retain the real backend lifecycle. Unsupported pause/resume and notification-delivery controls are not presented.

`/?service=<stable-service-id>` restores a selected monitor; `tab` and `stream` select its detail tab and evidence input. Service names save quietly on Enter or blur through an administrator-only `/v1/monitors/<id>/label` PATCH and persist in the database’s launch metadata. Workload names, IDs and subscriptions remain stable. Restart capture preserves saved service names. Detail settings exclude connection credentials.

**Create** opens monitoring setup. Input pickers retain the broker/entity labels and offer only entities with at least one numeric reading receiving fresh data, using the same 30-second activity predicate as **Online topics only**. Choices update with existing recording/preview observations and expire every second while the picker is open. Filtering does not change the selected entity, its configured readings, collection policies, or existing services. Setup links to Sources for recording configuration, then configures a static or adaptive detector using the acknowledged numeric input bindings. Starting remains disabled until collection is applied. A reading’s Configure monitoring link uses `/?create=monitoring&reading=<stable-reading-id>`; its input is preselected. Active ownership prevents a second service from claiming a reading. A successful launch opens the returned service ID.

Stars save service and reading favourites per account **in this browser**, alongside sidebar width and navigation. Service favourites have their own filter in the Monitoring list; reading favourites remain MQTT source shortcuts in the shared sidebar. Display-name edits do not break them. They do not alter catalogue structure or collection policy and are not included in catalogue export. Stored unresolved references are retained during temporary failures or loading. Personal grouping remains inactive.

Notification recipients remain deployment-managed. The existing anomaly email endpoint is preserved; this first version does not claim per-service subscriptions or a record of delivered alerts.

## Catalogue

Catalogue names and structural changes use the existing revisioned `/v1/system` database API and permission checks. Enter or leaving an inline name field saves; Escape cancels. A rejected or conflicting save is never presented as successful.

Shared groups remain part of the saved system definition and are labelled **Collections** in the sidebar, settings and structure editor. Their dropdown preserves the saved names and membership counts and opens each collection in the same sidebar. Personal grouping is currently removed from the interface: no membership editor, personal scopes, color overlays, or workspace export. Existing per-account personal group data remains in browser storage for later use. A previously selected personal scope falls back to the catalogue without deleting its saved groups. Ordinary navigation and sidebar visibility still persist per account.

Settings export the latest acknowledged database catalogue. Imports accept only `aberration-system` schema version 1 documents. Previous provider-specific catalogues and spatial workspace bundles are rejected before any save. Counts and scope are reviewed before explicit replacement at the captured database revision. Importing never starts a live connection.

## Performance and telemetry

TanStack Virtual renders the visible list and a small overscan buffer, including variable-height names. The navigation index and labels are built only when configuration changes. Live updates do not rebuild or reorder the catalogue. Search uses precomputed strings and limits its result list to 100 entries; refine the query for more specific matches. Service creation, service details, preview, chart code, settings, and the structure editor load separately. The explorer has no WebGL or Three.js dependency.

The existing schema limits still apply: 128 brokers, 2,048 entities, 4,096 readings, and a 1 MiB system definition. UI tests exercise 4,000 sibling topics and deeply nested MQTT paths. Supporting much larger catalogues will require server-side paging and indexed search in addition to the virtualized UI.

Live telemetry uses the existing backend MQTT session API. **Connect**, **Disconnect**, and **Retry** control the current view in every deployment. Connection states use the same labels for all data sources; generated feeds are identified separately as **Simulated data**. Values and limited history stay in memory; existing collection policies and monitoring services remain independent. Private brokers still require reachable networking and configured credential references. An imported catalogue alone does not provide that access. The isolated local deployment can run catalogue-shaped MQTT fixtures without changing the connection controls. Disconnected, waiting, and failed connections are shown honestly.

Reading charts reuse the details page's ECharts model, detector selection, threshold history, and event details. Score and evidence traces use clean continuous lines without sample markers; thresholds appear only as shaded alarm regions, without boundary lines. Missing evidence remains a gap, and inspection retains the exact score and threshold values. The time selector limits the history window relative to the latest available observation, so a quiet or stopped reading still opens with its last recorded data. The raw-data plot fits actual samples, with a visible marker for a single sample. Ctrl+scroll zooms, dragging pans, and the overview selects a range. Keyboard controls support +/−, Left/Right, and Home. Inspection holds absolute timestamps while new samples arrive; Full range returns to automatic fitting. Display-name edits preserve inspection; changing the input resets it.

Recorded numeric readings open without Connect: collection runs independently of the page, and their status reflects the persistent ingress rather than the temporary preview. Stored samples load independently of monitoring metadata, then poll with ingestion cursors every two seconds while the reading is visible. The latest numeric value uses the same history, showing the actual observation date and time even when no preview connection exists. A workspace-owned cache keeps up to 12 visited inputs and 32,768 combined telemetry/evidence observations. Returning displays cached data immediately while refreshing; after a longer absence it requests the latest bounded page rather than replaying an unlimited backlog. The cache is isolated by account, input definition and accepted identity, is discarded when the workspace closes, and does not subscribe to hidden readings. A fresh login loads history from the database. Boolean and text collection retain the existing latest-state persistence semantics.

The inspector's Collection controls explicitly select Off, Sample (1–3,600 seconds), or Original rate. Actions review their scope and any affected monitors before applying. Broker, entity, topic and catalogue-group scopes operate on their current reading IDs; new readings remain Off. Sources opens the same generic catalogue editor. Importing metadata does not activate a policy contained in a file: existing selections survive by stable reading ID and new entries remain unselected.

## Upgrade and deployment

The catalogue migrations and what they preserve are described in [Collection](../operations/system-collection.md).

There is one catalogue runtime and one accepted topic namespace. New readings receive deterministic internal entity and reading identities. JSON Pointer bindings support multiple fields on an arbitrary upstream MQTT topic. Importing or adding a reading leaves it Off; an existing selection is retained by stable reading ID. Active monitors must stop before an input or its collection cadence changes. Generated v1 EMQX/GOST routes are retired before generic subscriptions start; operator-authored routes are untouched.

Production readiness checks the generic catalogue's matching ingress and collector revision, including idle catalogues with all inputs Off. The ingress controller uses an independent advisory lock so it cannot block account administration or schema migrations. Preview and persistent collection share operator access configuration: network reachability, allowlists, credentials and TLS requirements determine access to private sources.

The production rehearsal exercises real upstream MQTT ingestion, recording, adaptive score/threshold evidence and browser monitoring journeys. Database backup/restore followed by repeated deployment checks retained accounts, favourites, catalogue and monitor settings, newly collected history and a single restarted worker. Synthetic brokers and disposable credentials belong only to the rehearsal.

Persistent selected subscriptions run in TACTIC independently of browser leases, forward raw envelopes through internal EMQX, and feed the existing bounded collector. Only admitted fresh numeric observations enter telemetry history and the accepted detector feed; boolean/text/identifier observations keep the existing latest-state persistence behavior. Retained snapshots establish state but do not become fresh detector input. Configuration generations prevent queued observations from an earlier mapping entering a new mapping. Explicit Off removes subscriptions and stops admission; existing numeric history is preserved. Active monitors must be paused before their inputs or collection cadence change.

Temporary Connect leases subscribe only to readings that need a preview in the focused scope and use the union of active viewers' selections. Recorded numeric readings use database history instead of a duplicate preview subscription. Browsing metadata without a focused selection opens no upstream subscriptions. Changing topics on a healthy broker updates subscriptions on the existing MQTT connection; leaving a broker releases its worker. Previously observed preview samples remain in the same fixed global buffer across scope resets and hidden-tab pauses, with timestamp deduplication when snapshots replay. Disconnect, account/input-definition changes and buffer limits still clear or expire temporary data. This path never activates collection or invents values for unobserved intervals. Collection status and latest recorded values poll a compact scoped API; stored history and monitoring evidence poll only for the selected reading. Scores and dynamic thresholds retain the details chart's behavior. The Configure monitoring link opens integrated service creation with the selected reading preselected and catalogue names displayed.

Operator broker allowlists, credential references and network access remain required. `SYSTEM_COLLECTION_ENABLED` controls persistent ingestion independently of `SYSTEM_LIVE_ENABLED`. The internal EMQX publisher uses the configured broker/TLS defaults and `SYSTEM_COLLECTION_MQTT_USERNAME`, `SYSTEM_COLLECTION_MQTT_API_KEY`, and `SYSTEM_COLLECTION_MQTT_CA_FILE`. Production mounts the existing proxy credential and CA as private TACTIC secrets; catalogue exports never contain them.

For an existing isolated local deployment, rebuild the frontend, API gateway, TACTIC, MQTT proxy, RADAR image and DB sync using the configured `dev/local` Compose project. Stop application writers, run the packaged migration action once, then run DB sync and recreate the application services. Preserve database volumes, existing monitor workloads and private configuration. Do not reapply the synthetic fixture when testing a saved private catalogue. See [local deployment](local-deployment.md) for initial setup.

## Shared interface

`App.css` owns semantic colors, typography, spacing and component states. `ApplicationWorkspace` owns the header, catalogue sidebar/drawer, resize control and a Suspense boundary around routed main content. `CatalogueProvider` owns one `useSystemDocument`, navigation index, live preview instance, account-scoped preferences and history cache. Runtime-only updates retain the document/index identity. `WorkspaceNavigation` supplies the navbar links; `AppHeader` and `ApplicationMenu` share preferences and account controls. `PageShell` sets content width and spacing. The explorer uses those tokens rather than a separate palette. Auth, forms, tables, menus, dialogs and empty/error/loading states use the same restrained surfaces. Quiet branding details remain part of the interface: authentication screens use the original repeating slash monogram behind the form, without animation or interaction layers over controls. Mobile controls have 44-pixel targets, including popover actions inside the explorer drawer. Broker and entity definitions display their actual catalogue metadata; user-provided labels and MQTT paths remain verbatim.

## Sources

`/sources` is a setup destination inside the shared layout. Entity selection shows
its metadata and registered readings; individual readings lead to their recording
configuration. Broker and topic policies retain their MQTT meaning across all
entities on that broker, with that scope explained in the topic inspector.
Catalogue settings supports adding entities and editing existing definitions,
including entities with no readings, without a separate entity directory.
Returning to Monitoring restores its previous inspection when the source matches,
or the explicit service setup return path. Unsaved recording changes block section
changes, broker changes and leaving a recording scope; cancellation preserves the
draft and source selection. Structural catalogue editing stays disabled while a
recording draft is dirty. Row selection changes the main content; chevrons browse.
Recording controls live here, with inheritance, child exceptions, future-reading opt-in,
preview counts, affected-monitor confirmation, and one Apply action. Members inspect
without editing. Catalogue settings remain available without opening automatically.

The catalogue settings dialog is owned by the shared layout in every section.
It shows the current catalogue's actual counts, explains each creation action, and
provides separate import and export rows and an existing-entity
chooser. A selected JSON file is reviewed with its name and contents before explicit
replacement at the captured revision. Export remains available when editing is
unavailable. The dialog follows both themes and reflows for narrow screens.

Monitoring remains the default destination. Setup detours preserve the service draft
and selected inputs in account-scoped memory. Returning through the navbar restores the
Monitoring URL, search, filters, sidebar positions, and chart inspection. The bounded
history cache and live-preview instance belong to the shared layout; unmounted charts stop polling. Logout
or account changes clear this memory. Colours use the shared semantic theme tokens.

## Reporting

Reporting uses the same selected source to filter events and summary metrics by
runtime entity/reading identities. Multivariate events match any participating
selected reading. Legacy multivariate events without a recorded sensor set match
only when the full runtime entity is selected. Missing sources produce an empty
scope with a clear reset action, rather than showing unrelated events.
