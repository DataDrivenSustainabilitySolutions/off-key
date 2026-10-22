# User guide — web app

This page explains end-user workflows in the React frontend.

## When to use this page

Use this page for account, charger, favourites, monitoring-service, and anomaly workflows in the UI.

## Audience

- Platform users and operators interacting with the web app.

## Main routes

| Route | Purpose | Access |
| --- | --- | --- |
| `/register` | Accept an invitation and set a password | Public |
| `/verify` | Retired; redirects to `/login` | Public |
| `/login` | Sign in | Public |
| `/forgot-password` | Request a password reset | Public |
| `/reset-password` | Set a new password with a reset token | Public |
| `/` | Monitoring services and selected-source evidence | Authenticated |
| `/details/:chargerId` | Telemetry details for one charger | Authenticated |
| `/monitoring/:chargerId` | Opens the Create workbench for this entity; shows the setup form when visual authoring is disabled | Authenticated |
| `/services` | Legacy link to Monitoring | Authenticated |
| `/sources` | Sources: configure brokers and recorded readings | Authenticated |
| `/anomalies` | Reporting: review recent anomaly events | Authenticated |
| `/account` | User profile and account actions | Authenticated |
| `/system/status` | Live collection diagnostics, database size and retention status | Authenticated |

## Workspace navigation

The catalogue opens and closes from the small handle on its upper edge. Desktop
collapse restores the full content width while preserving search, navigation and
the saved panel width. On mobile the catalogue overlays the page below the header;
its edge handle, Escape or the backdrop closes it and restores focus. Ctrl/Cmd+K
opens the catalogue and focuses search in either layout.

**Monitoring**, **Sources**, and **Reporting** are always available in the navbar,
including on mobile. The left sidebar contains one MQTT catalogue of brokers,
entities, topics and readings. Selecting a row scopes the current section; its
chevron browses the next level. Switching sections keeps the source selected and
retains the catalogue's search, branch and scroll position.

Monitoring shows services for the selected source and previews selected readings.
Sources shows source metadata and recording configuration. Selecting an entity
there lists its readings; choose one to configure recording. Reporting shows
events involving the selected source. **All sources** clears this filter without
moving the sidebar. The folder-and-hierarchy icon beside the sidebar count,
**Back to catalogue**, returns to the root and clears the search and source filter.
At the root it also scrolls the broker list to the top.

**Collections** opens named sets of related brokers, entities and readings in the
same sidebar. Collections are shared parts of the catalogue. Inside a branch,
the heading still opens the current path so you can jump to an ancestor.

The logo returns to dashboard home. The catalogue button beside it hides/reopens the desktop sidebar or
opens the mobile drawer. The section links remain in the navbar. A selected source
is included in the URL, so links and browser back/forward retain that context.

## Authentication workflow

1. Ask your organization administrator for an invitation.
2. Open the invitation link and choose a password of at least 12 characters.
3. Log in and receive a bearer token.
4. The frontend API client attaches that token to subsequent requests.

With **Remember this device**, the access token stays in memory and is restored from an HttpOnly session cookie through `/v1/auth/refresh`; otherwise it lives in session storage for the tab. In local development, invitation and password-reset messages are available in Mailpit at <http://localhost:8025>.

**Account → Access control** shows your signed-in email and role. Administrators manage
invitations, roles, and access under **Account → Members**. Disable a member to revoke
their access. Once disabled, **Remove** permanently deletes their account and personal
favorites after confirmation. Shared catalogue data, monitoring services and reports
are kept. A removed member needs a new invitation to return.
Members can view the shared workspace and edit their own favorites. Administrators
also manage data sources, monitors, and anomalies.

## Settings and system status

Open **Menu → Settings → Appearance** to choose **Light**, **Dark**, or
**Follow system**. Changes apply immediately and are saved in this browser on
this device. Follow system also responds to changes in the device's appearance.
Settings opens over the current page, preserving your workspace and unsaved input.
Close it with the close button or Escape to return to the page.

Open **Menu → Status** for live collection diagnostics, database size and
retention information. Collection status refreshes automatically every three
seconds; **Refresh storage** requests updated database measurements. The former
`/account/settings` diagnostic link redirects to `/system/status`.

Account management remains under **Menu → Account**. Catalogue configuration is
available from **Catalogue settings** at the bottom of the catalogue sidebar.

## Readings and telemetry workflow

1. Browse the MQTT catalogue or search for a reading.
2. Select the reading in **Monitoring** to open its preview and recorded history.
3. Use **Sources** to inspect or change its recording policy, then **Apply changes**.
4. Open its monitoring service to review detector evidence and configuration.

Existing entity detail links at `/details/:chargerId` show recorded readings with
category and time-range controls.

## Data-source activity

Topic and reading circles in the catalogue show activity from a live preview or
background recording. A filled circle means a fresh message arrived in the last
30 seconds. A hollow circle means the source is waiting for fresh data or is not
listening; hover or focus the row to see its description. Retained snapshots and
stored history do not count as fresh traffic. Browsing alone starts no collection.

The **Online topics only** filter icon beside **Back to catalogue** keeps filled-circle
readings and the paths leading to them. It also filters search, collections and reading
favourites, updates as traffic starts or becomes stale, and remembers your choice in
this browser. Turn it off to show the full catalogue again. Filtering keeps the
current source selected and does not start a connection or change recording.
An empty filtered list shows **No active topics** with an underlined **Show all
topics** action beneath it. This turns off the online filter and keeps your
current folder, search and source selection.

Configure recording under **Sources**. Broker and topic policies can cover several
readings; review the affected scope before applying changes. Including readings
added later requires an explicit opt-in. Administrators can also use **Connect**
to preview configured sources whose recording is off, and **Disconnect** to end
that preview. Previewing does not enable background recording.

## Favourites workflow

1. Star a service in Monitoring or a reading in its preview.
2. Select **Favourites** in the Monitoring service filters to show starred services.
3. Starred readings appear as source shortcuts in the catalogue sidebar.

These service and reading favourites are saved per account in this browser.

## Services workflow

The [visual monitoring guide](monitoring.md#visual-monitoring-pipelines) explains
templates, the typed graph, reading selection and live inspection.

Open **Monitoring** at `/` to inspect monitoring services. The view refreshes service state and shows the strategy and processing stage reported by the backend. Removing a service also releases its claimed readings.

## Reporting workflow

1. Open **Reporting** at `/anomalies`.
2. Review events grouped by charger.
3. Follow an event to the corresponding charger details.
4. Remove individual anomaly records when they are no longer required.

## Expected errors and operator actions

| UI message pattern | Typical cause | Action |
| --- | --- | --- |
| Login failed or unauthorized | Invalid credentials, expired session, or unverified account | Verify the account and sign in again |
| No brokers configured yet | The catalogue has no brokers | Add a broker in Sources or import a catalogue |
| Telemetry request failed | API or database latency/outage | Check API Gateway, TACTIC, and database health |
| Monitoring start failed | Invalid configuration, unavailable topic, or orchestration failure | Retry with defaults and inspect TACTIC logs |

## Related pages

- [Monitoring](monitoring.md)
- [Backend API](../reference/backend-api.md)
- [Testing and debugging](../development/testing-debugging.md)
