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
| `/favourites` | View favourite chargers | Authenticated |
| `/anomalies` | Review recent anomaly events | Authenticated |
| `/account` | User profile and account actions | Authenticated |

> [!NOTE]
> The current route uses British spelling: `/favourites`.

## Authentication workflow

1. Register with an email address and password.
2. Verify the account through the emailed link.
3. Log in and receive a bearer token.
4. The frontend API client attaches that token to subsequent requests.

The **Remember me** choice determines whether the browser stores the session in local or session storage. In local development, verification and password-reset messages are available in Mailpit at <http://localhost:8025>.

## Charger and telemetry workflow

1. Open `/` to list chargers.
2. Select a charger to open `/details/:chargerId`.
3. Select the telemetry type and time range.
4. Review the rendered charts and data.

## Favourites workflow

1. Add or remove a favourite from a charger view.
2. Open `/favourites` to see the current list.
3. Select a favourite to return to its charger details.

Favourites are scoped to the signed-in user.

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
