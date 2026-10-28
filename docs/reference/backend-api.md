# Backend API guide

This is the contract-oriented reference for the currently wired backend surfaces.

## When to use this page

Use this page when integrating a client, validating endpoint contracts, or triaging Gateway-to-TACTIC errors.

## Base URLs

| Service | Local base URL | Interactive schema |
| --- | --- | --- |
| API Gateway | `http://localhost:8000/v1` | `http://localhost:8000/docs` |
| TACTIC | `http://localhost:8001/api/v1` | `http://localhost:8001/docs` |

## Authentication expectations

| Endpoint group | Client behaviour | Current enforcement note |
| --- | --- | --- |
| Authentication | Public calls without a bearer token | Public by design |
| Chargers and telemetry | Send the login bearer token | Active, verified membership required |
| Monitors and anomalies | Send the login bearer token | Members read; administrators write |
| Favourites | Send the login bearer token | Server selects the current member as owner |
| Members | Send the login bearer token | Profile for self; administrators manage membership |
| Health and readiness | No token | Public operational probes in local deployments |
| Public demo | No token, only where `DEMO_MODE` is on | Listed reads as the demo viewer; everything else 403 |

!!! important
    Always send `Authorization: Bearer <token>` for non-authentication user workflows, and supply the private service credential only for trusted gateway-to-TACTIC calls.

## Gateway API — `/v1`

### Authentication

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `POST` | `/auth/register` | Retired: always returns 403 | Accounts require an invitation |
| `POST` | `/auth/accept-invitation` | Activate an invited account | Body: `token`, `password` |
| `POST` | `/auth/login` | Authenticate and mint a JWT | Body: `email`, `password` |
| `GET` | `/auth/verify-email` | Retired: always returns 410 | Request a new invitation |
| `POST` | `/auth/forgot-password` | Send reset mail when the account exists | Body: `email` |
| `POST` | `/auth/reset-password` | Reset a password | Body: `token`, `new_password` |
| `POST` | `/auth/refresh` | Rotate the remembered session cookie and mint a new JWT; 401 clears the cookie | Session cookie |
| `POST` | `/auth/logout` | Revoke the remembered session and clear its cookie | Session cookie |

```http
POST /v1/auth/login
Content-Type: application/json

{"email":"user@example.com","password":"<user-password>"}
```

```json
{
  "access_token": "<bearer-token>",
  "token_type": "bearer"
}
```

### Public demo

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `GET` | `/demo` | Whether signed-out visitors browse the read-only demo | None |

With `DEMO_MODE` on, a call without a bearer token reaches only the read
routes listed in `off_key_api_gateway.api.demo.GUEST_ROUTES`, signed in as the
configured viewer member; other calls answer 403. See
[Public demo](../operations/public-demo.md).

### Membership

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| `GET` | `/members/me` | Current profile | Active member |
| `GET` | `/members` | List organization members | Administrator |
| `POST` | `/members/invitations` | Invite or resend; body `email`, `role` | Administrator |
| `PUT` | `/members/{user_id}` | Set `role` and `is_active` | Administrator |
| `DELETE` | `/members/{user_id}` | Permanently remove a disabled member and personal favorites/sessions; 204 on success, 409 if active, 404 if missing | Administrator |

Roles are `admin` and `user` (member). Account and token lifecycle details are in
[Single-organization operation](../single-organization.md).

### Chargers and telemetry

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `GET` | `/chargers/available` | List chargers | Query: `skip`, `limit` |
| `GET` | `/chargers/active` | List active chargers | Query: `skip`, `limit` |
| `GET` | `/chargers/active/id` | List active charger identifiers | Query: `skip`, `limit` |
| `GET` | `/telemetry/{charger_id}/type` | List telemetry types | Query: `limit` |
| `GET` | `/telemetry/{charger_id}/data` | Fetch telemetry points | Query: `type`, `limit`, cursor fields, `paginated` |
| `GET` | `/telemetry/{charger_id}/range` | Fetch a downsampled range: each time bucket's lowest and highest value | Query: `type`, `start` (omit for all stored history), `end` (default now), `buckets` (10–2000, default 600) |

Telemetry cursors:

- Use `after_timestamp` for historical event-time pagination.
- Use `after_created` and `after_event_timestamp` together for live ingestion-order pagination.
- Do not mix historical and live cursor forms.

```http
GET /v1/telemetry/charger-123/data?type=controllerCpuUsage&limit=200
Authorization: Bearer <token>
```

### Generic catalogue and collection

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| `GET` | `/system` | Saved generic document, revision, bindings and runtime | Member |
| `PUT` | `/system` | Save structural changes at `expected_revision` | Administrator |
| `GET` | `/system/revisions` | Saved catalogue revisions | Member |
| `POST` | `/system/collection/status` | Scoped collector status and latest readings | Member |
| `POST` | `/system/collection/preview` | Review explicit collection changes and affected monitors | Administrator |
| `PUT` | `/system/collection` | Apply confirmed opt-in policies | Administrator |
| `POST` | `/system/connections/check` | One MQTT CONNECT to a saved broker, then disconnect; never subscribes | Administrator |
| `GET` | `/system/health` | Matching ingress/collector revision and status | Member |
| `GET` | `/system/storage` | Storage size and managed retention status | Member |
| `GET` | `/system/live` | Current preview session and samples after `after_sequence` | Member |
| `POST` | `/system/live/leases` | Start a bounded preview lease | Administrator |
| `PUT` | `/system/live/leases/{lease_id}` | Renew a preview lease | Administrator |
| `DELETE` | `/system/live/leases/{lease_id}` | Stop a preview lease; 204 | Administrator |

Catalogue documents use only `aberration-system` schema version 1. New inputs
remain Off regardless of policy metadata in an import. The UI reviews structural
replacement before saving; existing selections survive by stable reading ID.
`/sources` and the provider-specific catalogue endpoints have been removed.

The `/system/live` session API starts explicitly bounded in-memory previews.
Acquiring a lease requires an administrator; members can inspect an existing
session. Preview does not enable persistent collection. Accepted detector topics
use only `telemetry/<entity>/<reading>`; upstream topics can use arbitrary concrete
MQTT paths and JSON Pointer payload bindings.

### Monitoring and model discovery

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `GET` | `/monitors/all` | List services | `active_only`, `include_docker_status` |
| `GET` | `/monitors` | Get one service | Exactly one of `container_name`, `container_id` |
| `POST` | `/monitors/start` | Start a form-configured monitor as a pipeline (HTTP 202) | Monitoring configuration body |
| `DELETE` | `/monitors/stop` | Stop/remove a workload by container | Exactly one of `container_name`, `container_id` |
| `DELETE` | `/monitors/{service_id}` | Delete a service record and backing workload | Path: `service_id` |
| `PATCH` | `/monitors/{service_id}/label` | Rename a service; administrator only | Body: `display_name` |
| `GET` | `/monitors/models` | Discover available models | Optional `strategy` |
| `GET` | `/monitors/evidence` | List inference evidence | `charger_id`, optional `telemetry_type`, `limit` |
| `GET` | `/monitors/evidence/chart` | Incrementally load chart evidence | `charger_id`, optional complete cursor, `limit` |

The chart cursor is the complete tuple `after_created`, `after_timestamp`, `after_service_id`, and `after_sequence_number`; if one is supplied, all four are required.

A monitor start body contains:

- required `container_name` and `mqtt_topics`
- `monitoring`: the strategy configuration, including `strategy`
  (`static_baseline` or `adaptive_stream`), `model_type`, `model_params`, and
  the strategy's training, calibration, and alarm settings
- optional `performance_config` for sensor alignment

Omitting `monitoring` selects the default static baseline. The former top-level
`strategy`, `model_type`, `model_params`, `static_baseline_config`, and
`adaptive_stream_config` fields remain accepted at API ingress and are converted
to `monitoring`. Mixing the two formats, conflicting model fields, and malformed
configuration return HTTP 422. The gateway forwards only the canonical format to
TACTIC.

TACTIC converts the configuration into its equivalent graph, binds each topic to
its selected numeric catalogue reading and submits a pipeline activation, even
while the visual workbench is disabled. The HTTP 202 response carries
`service_id`, `activation_id`, `container_name`, `status` (the activation phase)
and `mqtt_topics`. Poll `/monitors/pipeline-activations/{activation_id}` until
the service exists. Topics without a selected numeric reading return HTTP 422.

Use `/monitors/models` as the source for valid model names and parameter schemas.

Visual monitoring interfaces use the same authenticated `/v1/monitors` prefix:

| Family | Paths | Purpose |
| --- | --- | --- |
| Catalog | `/pipelines/catalog` | Generated components, bounded field descriptors and templates |
| Library | `/pipelines`, `/pipelines/{id}`, `/pipelines/{id}/draft` | Inspect designs; administrators create, rename, archive and save with `expected_version` |
| Validation | `/pipelines/validate`, `/pipelines/{id}/validate` | Administrators infer bounded feature metadata and validate unsaved or saved graphs without changing library state |
| Revisions | `/pipelines/{id}/revisions`, `/pipelines/{id}/revisions/{revision_id}`, `/pipelines/{id}/revisions/{revision_id}/metadata` | Publish and inspect immutable executable revisions |
| Activations | `/pipelines/apply`, `/pipeline-activations`, `/pipeline-activations/{id}` | Apply a definition directly (HTTP 202), idempotent start/replacement, progress and cancellation |
| Bound run | `/{service_id}/pipeline`, `/{service_id}/pipeline-layout`, `/{service_id}/pipeline-history`, `/{service_id}/pipeline-metadata`, `/{service_id}/pipeline-state` | Immutable execution and retained history; separately versioned layout |
| Workspace | `/workspace?selected_service_id=...` | One member-scoped request for summaries and the selected bounded diagnostic snapshot |

Use publication and activation for graph starts. The legacy `/start` endpoint
remains compatible with existing callers; direct public graph launches are rejected
so they cannot bypass preflight, durable input reservations or run history.
Draft/layout conflicts return HTTP 409. Publishing does not activate a revision.
Run views survive deletion of the live service and expose retained input metadata,
terminal errors and compiler feature lineage. POST
`/pipelines/{id}/validate` accepts `{definition, selected_node_id?}`; GET
`/{service_id}/pipeline` accepts the same optional `selected_node_id` query for
member inspection even when authoring is disabled. Each compiler report is
bounded to 512 KiB, omitting provenance and then whole unselected node tables
with a `metadata_budget` notice. Complete ordered names for the selected node
and its immediate parents remain available; inspect `features_complete` and
`provenance_complete` before interpreting missing metadata. Invalid oversized
definition echoes use `definition: null` and `definition_omitted: true`; bounded
errors expose `issues_truncated`. Internal MQTT overrides and runtime image pins
are rejected by public monitor creation.
See [pipeline architecture and rollout](../development/monitoring-pipelines.md).

### Favourites and anomalies

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `GET` | `/favorites` | List a user's favourites | Current authenticated member |
| `POST` | `/favorites` | Add a favourite charger for the current member | Body: `charger_id` |
| `DELETE` | `/favorites` | Remove a favourite charger of the current member | Body: `charger_id` |
| `GET` | `/anomalies/count` | Count anomalies | Optional query: `since` |
| `GET` | `/anomalies` | List charger anomalies | `charger_id`, optional `telemetry_type`, `limit` |
| `POST` | `/anomalies` | Create an anomaly | JSON body, or the documented equivalent query fields |
| `DELETE` | `/anomalies/{anomaly_id}` | Delete by stable identity | Path: `anomaly_id` |

### Gateway health

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Gateway liveness; this route is outside the `/v1` prefix |

## TACTIC API — `/api/v1`

All business routes require `X-Off-Key-Service-Key`; collection and membership
administration additionally validate the end-user bearer token. TACTIC is private.
Health and readiness remain available without this service credential.

### Data adapter

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/data/chargers` | Charger listing |
| `GET` | `/data/chargers/active/ids` | Active charger IDs |
| `GET` | `/data/telemetry/{charger_id}/types` | Telemetry type list |
| `GET` | `/data/telemetry/{charger_id}` | Telemetry points |
| `GET` | `/data/telemetry/{charger_id}/range` | Downsampled telemetry range |
| `POST` | `/data/auth/login` | Internal authentication check |
| `GET` | `/data/users/{user_id}/favorites` | List favourites |
| `POST` | `/data/users/{user_id}/favorites` | Add a favourite |
| `DELETE` | `/data/users/{user_id}/favorites/{charger_id}` | Remove a favourite |
| `GET` | `/data/anomalies/count` | Count anomalies |
| `GET` | `/data/anomalies/{charger_id}` | List anomalies |
| `POST` | `/data/anomalies` | Create an anomaly |
| `DELETE` | `/data/anomalies/{anomaly_id}` | Delete an anomaly |
| `GET` | `/data/monitoring-evidence/{charger_id}` | List monitoring evidence |
| `GET` | `/data/monitoring-evidence/{charger_id}/chart` | Load chart evidence with a stable cursor |

### RADAR orchestration

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/orchestration/radar/services/` | List services |
| `POST` | `/orchestration/radar/services/start/` | Start a form-configured monitor as a pipeline activation |
| `GET` | `/orchestration/radar/services/details/` | Get workload details |
| `DELETE` | `/orchestration/radar/services/stop/` | Stop by container reference |
| `DELETE` | `/orchestration/radar/services/{service_id}` | Delete by service identifier |

### Model catalogue

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/models/` | List the detectors shipped in RADAR, optionally filtered by `strategy` |

The catalogue is served from code (`off_key_core.models`). Adding a model means
shipping its implementation and catalogue entry.

### Middleware health

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness; outside `/api/v1` |
| `GET` | `/ready` | Docker API readiness; outside `/api/v1` |

## Error model

| Status | Typical meaning |
| --- | --- |
| `200` / `201` | Successful read or mutation |
| `400` | Malformed request or unsupported transition |
| `401` / `403` | Authentication or authorization failure |
| `404` | Target not found |
| `409` | Duplicate or conflicting state |
| `422` | Semantic/input validation failure |
| `500` / `502` / `503` | Application, upstream, or infrastructure failure |

FastAPI validation errors and Gateway-propagated TACTIC errors use a `detail` field; exact payload shape varies by layer.

## Compatibility notes

- The current active-ID Gateway route is singular: `/chargers/active/id`.
- The Gateway API family remains `/favorites`. The dashboard's Favorites filter uses `/?state=favorites`; the old `/favourites` frontend route redirects there.
- Removed sync and preprocessor-discovery routes must not be used by new clients.

## Related pages

- [Architecture](../development/architecture.md)
- [Data model](data-model.md)
- [Testing and debugging](../development/testing-debugging.md)
- [Web app](../user-guide/web-app.md)
