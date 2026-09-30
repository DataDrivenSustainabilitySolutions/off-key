# User guide — web app

This page explains end-user workflows in the React frontend.

## When to use this page

Use this page for account, charger, favourites, monitoring-service, and anomaly workflows in the UI.

## Audience

- Platform users and operators interacting with the web app.

## Main routes

| Route | Purpose | Access |
| --- | --- | --- |
| `/register` | Create an account | Public |
| `/verify` | Verify an email address | Public |
| `/login` | Sign in | Public |
| `/forgot-password` | Request a password reset | Public |
| `/reset-password` | Set a new password with a reset token | Public |
| `/` | Charger overview dashboard | Authenticated |
| `/details/:chargerId` | Telemetry details for one charger | Authenticated |
| `/monitoring/:chargerId` | Configure monitoring for one charger | Authenticated |
| `/services` | Inspect and remove monitoring services | Authenticated |
| `/?state=favorites` | Dashboard filtered to favourite chargers | Authenticated |
| `/anomalies` | Review recent anomaly events | Authenticated |
| `/account` | User profile and account actions | Authenticated |

!!! note
    Existing `/favourites` bookmarks redirect to the dashboard's Favorites filter.

## Authentication workflow

1. Ask your organization administrator for an invitation.
2. Open the invitation link and choose a password of at least 12 characters.
3. Log in and receive a bearer token.
4. The frontend API client attaches that token to subsequent requests.

The **Remember me** choice determines whether the browser stores the session in local or session storage. In local development, invitation and password-reset messages are available in Mailpit at <http://localhost:8025>.

Administrators manage invitations, roles, and access under **Account → Organization members**.
Members can view the shared workspace and edit their own favorites. Administrators
also manage data sources, monitors, and anomalies.

## Charger and telemetry workflow

1. Open `/` to list chargers.
2. Select a charger to open `/details/:chargerId`.
3. Select the telemetry type and time range.
4. Review the rendered charts and data.

## Data-source activity

Open `/sources`, expand a broker and charger, and inspect the badge beside each
measurement. **Recent data** confirms a live reading within three saved sampling
intervals, with a minimum window of one minute. Original-rate sensors use one
minute. **No recent data** shows an older live reading; **Retained snapshot** is
cached MQTT data; **No data yet** means no observation has arrived. The receipt
time appears beside observed measurements.

Activity reflects saved settings. Measurements with collection off are not
observed. Unsaved changes to a broker, charger binding, sensor topic, or value
type show **Save to observe**. **Status unavailable** means live status could not
be confirmed, including stale worker reports.

## Favourites workflow

1. Add or remove a favourite from a charger view.
2. Select **Favorites** under **Charger State** on the dashboard to see the current list. Search and card/table views work with this filter.
3. Select a favourite to return to its charger details.

Favourites are scoped to the signed-in user. Removing a favourite immediately
removes it from the filtered list; if saving fails, it is restored.

## Services workflow

Open `/services` to inspect monitoring services. The view refreshes service state and shows the strategy and processing stage reported by the backend. Removing a service also releases its claimed sensors.

## Anomaly workflow

1. Open `/anomalies`.
2. Review events grouped by charger.
3. Follow an event to the corresponding charger details.
4. Remove individual anomaly records when they are no longer required.

## Expected errors and operator actions

| UI message pattern | Typical cause | Action |
| --- | --- | --- |
| Login failed or unauthorized | Invalid credentials, expired session, or unverified account | Verify the account and sign in again |
| No chargers found | No telemetry has been ingested | Validate the source MQTT or simulator path |
| Telemetry request failed | API or database latency/outage | Check API Gateway, TACTIC, and database health |
| Monitoring start failed | Invalid configuration, unavailable topic, or orchestration failure | Retry with defaults and inspect TACTIC logs |

## Related pages

- [Monitoring](monitoring.md)
- [Backend API](../reference/backend-api.md)
- [Testing and debugging](../development/testing-debugging.md)
