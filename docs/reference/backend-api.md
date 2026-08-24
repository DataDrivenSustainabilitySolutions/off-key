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
| Chargers and telemetry | Send the login bearer token | Some routes are currently permissive at route level |
| Monitors, favourites, and anomalies | Send the login bearer token | Preserve token behaviour; server policy may tighten |
| Health and readiness | No token | Public operational probes in local deployments |

> [!IMPORTANT]
> Always send `Authorization: Bearer <token>` for non-authentication user workflows, even if a local route currently accepts an unauthenticated request.

## Gateway API — `/v1`

### Authentication

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `POST` | `/auth/register` | Register a user and send verification mail | Body: `email`, `password`, optional `role` |
| `POST` | `/auth/login` | Authenticate and mint a JWT | Body: `email`, `password` |
| `GET` | `/auth/verify-email` | Verify an account token | Query: `token` |
| `POST` | `/auth/forgot-password` | Send reset mail when the account exists | Body: `email` |
| `POST` | `/auth/reset-password` | Reset a password | Body: `token`, `new_password` |

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

### Chargers and telemetry

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `GET` | `/chargers/available` | List chargers | Query: `skip`, `limit` |
| `GET` | `/chargers/active` | List active chargers | Query: `skip`, `limit` |
| `GET` | `/chargers/active/id` | List active charger identifiers | Query: `skip`, `limit` |
| `GET` | `/telemetry/{charger_id}/type` | List telemetry types | Query: `limit` |
| `GET` | `/telemetry/{charger_id}/data` | Fetch telemetry points | Query: `type`, `limit`, cursor fields, `paginated` |

Telemetry cursors:

- Use `after_timestamp` for historical event-time pagination.
- Use `after_created` and `after_event_timestamp` together for live ingestion-order pagination.
- Do not mix historical and live cursor forms.

```http
GET /v1/telemetry/charger-123/data?type=controllerCpuUsage&limit=200
Authorization: Bearer <token>
```

### Monitoring and model discovery

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `GET` | `/monitors/all` | List services | `active_only`, `include_docker_status` |
| `GET` | `/monitors` | Get one service | Exactly one of `container_name`, `container_id` |
| `POST` | `/monitors/start` | Start a RADAR service | Monitoring configuration body |
| `DELETE` | `/monitors/stop` | Stop/remove a workload by container | Exactly one of `container_name`, `container_id` |
| `DELETE` | `/monitors/{service_id}` | Delete a service record and backing workload | Path: `service_id` |
| `GET` | `/monitors/models` | Discover available models | Optional `strategy` |
| `GET` | `/monitors/evidence` | List inference evidence | `charger_id`, optional `telemetry_type`, `limit` |
| `GET` | `/monitors/evidence/chart` | Incrementally load chart evidence | `charger_id`, optional complete cursor, `limit` |

The chart cursor is the complete tuple `after_created`, `after_timestamp`, `after_service_id`, and `after_sequence_number`; if one is supplied, all four are required.

A monitor start body contains:

- required `container_name` and `mqtt_topics`
- `strategy`: `static_baseline` or `adaptive_stream`
- the matching `static_baseline_config` or `adaptive_stream_config`
- optional `model_type`, `model_params`, and `performance_config`

Use `/monitors/models` as the source for valid model names and parameter schemas.

### Favourites and anomalies

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `GET` | `/favorites` | List a user's favourites | Query: `user_id` |
| `POST` | `/favorites` | Add a favourite charger | Body: `user_id`, `charger_id` |
| `DELETE` | `/favorites` | Remove a favourite charger | Body: `user_id`, `charger_id` |
| `GET` | `/anomalies/count` | Count anomalies | Optional query: `since` |
| `GET` | `/anomalies` | List charger anomalies | `charger_id`, optional `telemetry_type`, `limit` |
| `POST` | `/anomalies` | Create an anomaly | JSON body, or the documented equivalent query fields |
| `DELETE` | `/anomalies/{anomaly_id}` | Delete by stable identity | Path: `anomaly_id` |

### Gateway health

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Gateway liveness; this route is outside the `/v1` prefix |

## TACTIC API — `/api/v1`

### Data adapter

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/data/chargers` | Charger listing |
| `GET` | `/data/chargers/active/ids` | Active charger IDs |
| `GET` | `/data/telemetry/{charger_id}/types` | Telemetry type list |
| `GET` | `/data/telemetry/{charger_id}` | Telemetry points |
| `POST` | `/data/auth/login` | Internal authentication check |
| `GET` | `/data/users/{email}` | Read a user |
| `POST` | `/data/users` | Create a user |
| `PATCH` | `/data/users/{email}/verify` | Mark a user verified |
| `PATCH` | `/data/users/{email}/password` | Update a password hash |
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
| `POST` | `/orchestration/radar/services/start/` | Start a service |
| `GET` | `/orchestration/radar/services/details/` | Get workload details |
| `DELETE` | `/orchestration/radar/services/stop/` | Stop by container reference |
| `DELETE` | `/orchestration/radar/services/{service_id}` | Delete by service identifier |
| `GET` | `/orchestration/radar/models/` | List model options |

### Model registry

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/models/` | List active models |
| `GET` | `/models/info/{model_type}` | Get model details |
| `POST` | `/models/validate` | Validate parameters |
| `POST` | `/models/create-instance` | Instantiate and validate a model |
| `GET` | `/models/categories/models` | List model families |
| `GET` | `/models/health` | Registry health |

Admin routes under `/admin/models` provide create, update, deactivate, list, and instantiation-test operations. Restrict these routes at the deployment boundary until route-level authorization is enforced.

### Middleware health

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness; outside `/api/v1` |
| `GET` | `/ready` | Model registry and Docker API readiness; outside `/api/v1` |

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
- The Gateway API family remains `/favorites`; `/favourites` is only the frontend route spelling.
- Removed sync and preprocessor-discovery routes must not be used by new clients.

## Related pages

- [Architecture](../development/architecture.md)
- [Data model](data-model.md)
- [Testing and debugging](../development/testing-debugging.md)
- [Web app](../user-guide/web-app.md)
