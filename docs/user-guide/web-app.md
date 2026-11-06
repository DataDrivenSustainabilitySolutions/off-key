# User guide — web app

This page explains end-user workflows in the React frontend.

## When to use this page

Use this page for account, entity, favourites, monitoring-service, and anomaly workflows in the UI.

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
| `/services` | Legacy link to Monitoring | Authenticated |
| `/sources` | Sources: configure brokers and recorded readings | Authenticated |
| `/anomalies` | Reporting: review recent anomaly events | Authenticated |
| `/dojo` | Dojo: datasets, labels, offline runs and comparisons; `?dataset=<id>&tab=values\|runs\|compare` opens one dataset | Members who may use the Dojo |
| `?settings=<section>` | Settings overlay above any workspace page: `account`, `preferences`, `catalogue` or `status` | Authenticated |
| `/account` | Legacy link: opens the Account settings section above Monitoring | Authenticated |
| `/system/status` | Legacy link: opens the System status settings section above Monitoring | Authenticated |

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

**Account → Signed in** shows your email, your role and what it lets you change.
Members whose role can manage members handle invitations, roles and access under
**Account → Members** and **Account → Roles**. Disable a member to revoke
their access. Once disabled, **Remove** permanently deletes their account and personal
favorites after confirmation. Shared catalogue data, monitoring services and reports
are kept. A removed member needs a new invitation to return.
Every member can view the shared workspace and edit their own favorites. A role
adds permissions to manage sources, monitors, alarms or members; Administrator
holds all of them. Controls a role does not cover stay hidden.

## Settings and system status

Open **Menu → Settings → Appearance** to choose **Light**, **Dark**, or
**Follow system**. Changes apply immediately and are saved in this browser on
this device. Follow system also responds to changes in the device's appearance.
Settings opens over the current page, preserving your workspace and unsaved input.
Close it with the close button or Escape to return to the page.

Account, Preferences, Catalogue and System status share one settings overlay. It
opens above the page you are on, which keeps running underneath, and closing it
(the close button, Escape, a click outside or the browser's Back button) returns
you to that page as you left it. The open section is part of the address, for
example `/sources?settings=status`, so it can be linked to and survives a reload.
Switching sections does not add browser history.

Open **Menu → System status** for live collection diagnostics, database size and
retention information. Collection status refreshes automatically every three
seconds; **Refresh storage** requests updated database measurements. The former
`/system/status` and `/account/settings` links open this section above Monitoring.

**Menu → Account** shows who is signed in and, for members who manage members, member access and roles.
Catalogue configuration opens from **Catalogue settings** at the bottom of the
catalogue sidebar as the overlay's Catalogue section; adding or editing an entry
opens the editor on top of it.

## Readings and telemetry workflow

1. Browse the MQTT catalogue or search for a reading.
2. Select the reading in **Monitoring** to see its latest value, age and history.
   Hover over the age for the exact timestamp or open **Source details** for the catalogue path.
3. Switch to **Sources** to inspect or change the selected reading's recording policy.
4. Open its monitoring service to review detector evidence and configuration.

Existing entity detail links at `/details/:chargerId` show recorded readings with
category and time-range controls.

## Data-source activity

Topic and reading circles in the catalogue show activity from a live preview or
background recording. A filled circle means a fresh message arrived in the last
30 seconds. A hollow circle means the source is waiting for fresh data or is not
listening; hover or focus the row to see its description. Retained snapshots and
stored history do not count as fresh traffic. Browsing alone starts no collection.

The **Recently active** filter icon beside **Back to catalogue** keeps filled-circle
readings and the paths leading to them. It also filters search, collections and reading
favourites, updates as traffic starts or becomes stale, and remembers your choice in
this browser. Turn it off to show the full catalogue again. Filtering keeps the
current source selected and does not start a connection or change recording.
An empty filtered list shows **No active topics** with an underlined **Show all
topics** action beneath it. This turns off the online filter and keeps your
current folder, search and source selection.

Configure recording under **Sources**. Broker and topic policies can cover several
readings; review the affected scope before applying changes. Including readings
added later requires an explicit opt-in. Roles that manage sources can also use **View live**
to preview configured sources whose recording is off, and **Stop live view** to end
that preview. Previewing does not enable background recording.

## Favourites workflow

1. Star a service in Monitoring or a reading in its preview.
2. Select **Favourites** in the Monitoring service filters to show starred services.
3. Starred readings appear as source shortcuts in the catalogue sidebar.

Favourites belong to your account and follow you to every browser. Agents and
scripts read and change the same list through `/v1/favorites`.

## Services workflow

The [visual monitoring guide](monitoring.md#visual-monitoring-pipelines) explains
templates, the typed graph, reading selection and live inspection.

Open **Monitoring** at `/` to inspect monitoring services. The view refreshes service state and shows the strategy and processing stage reported by the backend. Removing a service also releases its claimed readings.

## Reporting workflow

1. Open **Reporting** at `/anomalies`.
2. Review events grouped by entity.
3. Follow an event to the corresponding entity details.
4. Remove individual anomaly records when they are no longer required.

## Dojo workflow

The Dojo tries detection designs on stored data before anything is monitored
live. Nothing in it claims readings, starts monitors or writes to Reporting.

1. Open **Dojo** at `/dojo`. **Upload CSV** copies a file into a new dataset;
   **Copy recorded readings** copies the numeric readings of the entity or
   reading selected in the catalogue for a time window. A dataset is frozen:
   retention and catalogue edits never change it.
2. Open a dataset. **Values and labels** shows its series; zoom the chart to a
   known problem and choose **Use the zoomed range**, or type the window, then
   **Add label**. Labels may touch but not overlap.
3. **Runs** starts a run: choose a template or a design from the library, check
   which series feeds each input, and start it. The run replays the dataset in
   time order through the same alignment, learning and scoring as a live
   monitor; its progress updates while it runs.
4. **Compare** puts up to three finished runs side by side: their alarms under
   the values, how many labels each detected and how soon, and how many false
   alarms each raised per day outside the labels. The best value of a metric is
   bold. Editing a label re-scores every run at once.
5. **Use as template**, on a finished run, saves its design to the template
   library; it needs the permission to manage monitors. **Start a monitor**
   then opens the template in Monitoring with each input set to the recorded
   reading its series was copied from, where that reading is still collected
   and fits. Inputs fed by an uploaded series are chosen there.

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
