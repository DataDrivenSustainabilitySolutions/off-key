# Backend API guide

This is the contract-oriented reference for the currently wired backend surfaces.

## When to use this page

Use this page when integrating a client, validating endpoint contracts, or triaging Gateway-to-TACTIC errors.

## Base URLs

| Service | Local base URL | Interactive schema |
| --- | --- | --- |
| API Gateway | `http://localhost:8000/v1` | `http://localhost:8000/docs` |
| TACTIC | `http://localhost:8001/api/v1` | `http://localhost:8001/docs` |

Deployed installations serve the gateway under `/api` on the dashboard host and
start it with `--root-path /api`. Its schema at `/api/openapi.json` therefore
names `/api` under `servers`, and the interactive schema opens at `/api/docs`.

The gateway's OpenAPI document is written for clients that read it instead of
this page, AI agents included. Every operation is named after its handler, has
a description, and protected operations declare the `bearerAuth` scheme rather
than an `Authorization` parameter. The document's introduction maps the web
app's words (sources, readings, monitors, alarms) to the API's. Contract tests
in `backend/tests/contracts/test_gateway_openapi.py` keep it that way.

## Authentication expectations

| Endpoint group | Client behaviour | Current enforcement note |
| --- | --- | --- |
| Authentication | Public calls without a bearer token | Public by design |
| Demo status | Public call without a bearer token | Reports whether this installation allows public reads; contains no credentials |
| Devices and measurements | Send the login bearer token | Active, verified membership required |
| Monitors and alarms | Send the login bearer token | Members read; writes need `manage_monitors` or `manage_alarms` |
| Favourites | Send the login bearer token | Server selects the current member as owner |
| Members and roles | Send the login bearer token | Profile and roles for every member; `manage_members` changes them |
| Agents | Send the agent's key as the bearer token | A key reaches only operations marked `x-agent-access`; `manage_members` creates and revokes keys |
| Health and readiness | No token | Public operational probes in local deployments |

!!! important
    Always send `Authorization: Bearer <token>` for non-authentication user workflows, and supply the private service credential only for trusted gateway-to-TACTIC calls.

An explicitly enabled [public demo](../operations/public-demo.md) also accepts
anonymous requests on its read allowlist. Every unlisted anonymous request is
refused. Administrator tokens continue to use normal membership and permissions.

## Gateway API — `/v1`

### Public demo status

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| `GET` | `/demo` | Public-access capability and source attribution; `enabled: false` on ordinary installations | Public |

### Authentication

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `POST` | `/auth/accept-invitation` | Activate an invited account | Body: `token`, `password` |
| `POST` | `/auth/login` | Authenticate and mint a JWT | Body: `email`, `password` |
| `POST` | `/auth/password-reset` | Send reset mail when the account exists; the answer is the same either way | Body: `email` |
| `POST` | `/auth/password-reset/confirm` | Set a new password with the token from the reset mail | Body: `token`, `new_password` |
| `POST` | `/auth/refresh` | Rotate the remembered session cookie and mint a new JWT; 401 clears the cookie | Session cookie |
| `POST` | `/auth/logout` | Revoke the supplied bearer token and remembered session, then clear its cookie | Current bearer token and session cookie, when present |

```http
POST /v1/auth/login
Content-Type: application/json

{"email":"user@example.com","password":"<user-password>"}
```

```json
{
  "access_token": "<bearer-token>",
  "token_type": "bearer",
  "member_id": 7
}
```

### Membership

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| `GET` | `/me` | Current profile | Active member |
| `GET` | `/members` | List organization members | `manage_members` |
| `POST` | `/invitations` | Invite or resend; body `email`, `role` | `manage_members` |
| `PATCH` | `/members/{member_id}` | Change `role`, `is_active` or both; fields left out keep their value | `manage_members` |
| `DELETE` | `/members/{member_id}` | Permanently remove a disabled member and personal favorites/sessions; 204 on success, 409 if active, 404 if missing | `manage_members` |
| `GET` | `/permissions` | Every permission a role can grant, with a description | Active member |
| `GET` | `/roles` | Roles with their permissions and how many members hold each | Active member |
| `POST` | `/roles` | Create a role; body `name`, `permissions`; the id is derived from the name | `manage_members` |
| `PATCH` | `/roles/{role_id}` | Rename a role or replace its permissions | `manage_members` |
| `DELETE` | `/roles/{role_id}` | Delete a role no member holds; 204 | `manage_members` |
| `GET` | `/agents` | Agents that hold a key, each with the end of its key and what it may start | `manage_members` |
| `POST` | `/agents` | Create an agent and its key; body `name` and `starts` (`nothing`, `shadow` or `live`; `nothing` when left out). The answer carries `key` this once | `manage_members` |
| `PATCH` | `/agents/{agent_id}` | Set what the key may start; body `starts` | `manage_members` |
| `DELETE` | `/agents/{agent_id}` | Revoke the key, which stops working at once; 204. Services the agent started keep running | `manage_members` |
| `GET` | `/agents/me` | The agent a key belongs to and what it may start | A key |

Every active member can read everything outside the Dojo. A role grants the
permissions:
`manage_sources` (catalogue, collection and live preview), `manage_monitors`
(monitors and pipelines), `manage_alarms` (creating and deleting alarms),
`use_dojo` (the Dojo, reads included) and `manage_members` (members and roles). `GET /me` returns the member's
`role` and the `permissions` it grants. Two roles are built in: `admin`
(Administrator) always holds every permission and cannot be changed, and `user`
(Member) is what an invitation gives unless it names another role. Neither can be
deleted. A change that would leave no active member able to manage members is
refused with 409. Account and token lifecycle details are in
[Single-organization operation](../single-organization.md).

#### Keys for agents

An agent sends its key as `Authorization: Bearer <key>` in place of a member's
token. A key starts with `offkey_`, is shown once when it is created and is
stored only as a digest. It has no role and no permissions. What it may call is
decided per operation, and the gateway's OpenAPI document marks each such
operation with `x-agent-access`:

- `any`: every key. These are the reads an agent designs with (devices,
  readings and their measurements and profile, pipeline components, designs,
  monitors and their pipelines, evidence and alarms), validating and editing a
  design that is not saved, testing a design on history in the Dojo (copying
  history into a dataset, starting a run and reading its results), and
  proposing a design to a member, reading proposals and withdrawing its own.
- `start`: only a key whose `starts` is `shadow` or `live`. These are
  `POST /pipelines/apply`, which starts a monitoring service, and cancelling an
  activation. A key with `shadow` starts shadow runs only: a start without
  `shadow` set answers 403. A key cannot replace a running service:
  `replace_monitor_id` answers 403.

Every other operation answers a key with 403, among them stopping, renaming
and deleting monitors, deciding on a proposal, changing the library, labels
and datasets in the Dojo, sources, members, roles and the keys themselves. A new operation is closed to
keys until it is marked.

An agent that speaks the Model Context Protocol does not have to call these
operations itself: it finds them as tools at `/v1/mcp`, see
[MCP server for agents](#mcp-server-for-agents).

### Devices and measurements

Devices and readings are named by their catalogue ids, `devices[].id` and
`readings[].id` of `GET /v1/catalogue`. The installation resolves where their
values are stored.

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `GET` | `/devices` | Catalogue devices with their `reading_ids`, `online` and `last_seen` | Query: optional `active` |
| `GET` | `/devices/{device_id}/readings` | The catalogue readings of one device | Path: `device_id` |
| `GET` | `/readings/{reading_id}/measurements` | Recorded values of one reading | Query: `limit`, cursor fields, `paginated` |
| `GET` | `/readings/{reading_id}/measurements/buckets` | Recorded history as original samples, averages with ranges, or legacy extrema | Query: `start` (omit for all stored history), `end` (default now), `buckets` (10–2000, default 600), optional `view` (`auto` or `raw`), `window_ms` |
| `GET` | `/readings/{reading_id}/profile` | What the reading looks like: interval, range, gaps, daily and weekly rhythm, flat spells | Query: `days` (1–90, default 14) |

With `view=auto`, dense ranges return epoch-aligned bucket means calculated from
the original measurements, plus `minimum`, `maximum`, `count`, `start` and `end`.
Sparse ranges return original samples. `window_ms` optionally sets a minimum
averaging interval (1–86,400,000 ms); wider ranges may require a larger interval.
`view=raw` always returns original samples, capped at the newest 10,000. Both
views use an envelope with `representation` (`raw` or `mean`), `points`,
`interval_ms`, `sample_count`, `extent` and `truncated`. Counts and extent describe
the whole requested range, including samples omitted by the raw cap. Empty
buckets are omitted. Without `view`, the response remains the legacy list of
bucket extrema.

A profile says what a reading looks like, so a design can be fitted to it
without reading its history:

```http
GET /v1/readings/stream:dc-current/profile?days=14
```

| Field | Meaning |
| --- | --- |
| `first`, `last` | The earliest and latest value in the window |
| `coverage` | Share of the time between them that holds values, from 0 to 1, counted in buckets of `bucket_seconds` |
| `longest_outage_seconds` | The longest stretch without a value |
| `minimum`, `maximum` | How far the values reach |
| `daily_rhythm` | Share of the variation that the hour of the day explains, from 0 to 1; near 0 for a reading without a daily pattern. Null below two days |
| `weekly_rhythm` | Share that the day of the week and the hour together explain. Well above `daily_rhythm`, weekdays differ. Null below fourteen days |
| `level_change` | How far the level moved from the first day to the last, in spreads of the reading |
| `recent.interval_seconds`, `recent.interval_p90_seconds` | The usual time between two values, and the time nine in ten arrive within. Far apart, the reading reports on change |
| `recent.gaps`, `recent.longest_gap_seconds` | Pauses longer than five usual intervals |
| `recent.mean`, `recent.spread`, `recent.median`, `recent.p05`, `recent.p95` | Where the values lie |
| `recent.typical_change` | The usual change from one value to the next; against `spread` it says how noisy the reading is |
| `recent.flat_share`, `recent.longest_flat_seconds` | How often and how long the reading stays the same |
| `recent.distinct`, `recent.levels` | How many different values there are, and the values where there are at most ten |

The window fields come from the lowest and highest value of each bucket, so
they hold for windows of any length. `recent` looks at the newest values one by
one, up to 5000 of them. A window without values answers with nulls.

Measurement cursors:

- Use `after_timestamp` for historical event-time pagination.
- Use `after_created` and `after_event_timestamp` together for live ingestion-order pagination.
- Do not mix historical and live cursor forms.

```http
GET /v1/readings/stream:cpu-usage/measurements?limit=200
Authorization: Bearer <token>
```

### Catalogue, recording and live views

The catalogue `document` holds `brokers`, `devices`, `readings` and `groups`;
devices and readings name their broker as `broker_id`. A broker's `protocol` is
`mqtt` or `http`. On an HTTP broker a reading's `topic` is its request path,
and the reading may carry a `timestamp_pointer`; the field is absent from
readings that have none. Changes need
`manage_sources`, which TACTIC checks.

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| `GET` | `/catalogue` | Saved document, revision, how each reading is recorded (`runtime.bindings`) and `can_edit` | Member |
| `PUT` | `/catalogue` | Save structural changes at `expected_revision` | `manage_sources` |
| `GET` | `/catalogue/revisions` | Saved catalogue revisions | Member |
| `POST` | `/brokers/check` | One MQTT CONNECT to a saved broker (`broker_id`), then disconnect; never subscribes. For an HTTP broker, one `GET` for the path of its first reading | `manage_sources` |
| `POST` | `/brokers/{broker_id}/reconnect` | Restart recording from a broker now, resetting its retry backoff | `manage_sources` |
| `PUT` | `/recording` | Apply confirmed recording policies for `reading_ids`, or `rule_changes` for a broker, topic or reading scope | `manage_sources` |
| `POST` | `/recording/preview` | Review a recording change and the monitors it affects | `manage_sources` |
| `POST` | `/recording/status` | Recording state and latest values of the given `reading_ids` | Member |
| `GET` | `/recording/health` | Recording `diagnosis` (first failing check, with code and explanation) plus the raw ingress/collector reports | Member |
| `GET` | `/storage` | Storage size and managed retention status | Member |
| `GET` | `/live/measurements` | Open live views: brokers, readings and samples after `after_sequence` | Member |
| `POST` | `/live/views` | Open a bounded live view of `reading_ids`; answers its `view_id` and first `measurements` | `manage_sources` |
| `POST` | `/live/views/{view_id}/renew` | Keep a live view open, optionally with other `reading_ids` | `manage_sources` |
| `DELETE` | `/live/views/{view_id}` | Close a live view; 204 | `manage_sources` |

Catalogue documents use only `aberration-system` schema version 1. New inputs
remain Off regardless of policy metadata in an import. The UI reviews structural
replacement before saving; existing selections survive by stable reading ID.
Files exported before the rename, with `connections`, `streams` and
`connection_id`, still import.

`/recording/health` decides the recording diagnosis on the server. The checks run
in a fixed order (catalogue saved, collector report younger than 15 seconds,
local MQTT connected, revisions applied, broker routes, broker connections,
database, traffic) and the first that fails is returned as `diagnosis.code` with
a title, tone and explanation. The web app shows that verdict unchanged; it only
adds "Status not refreshing" when the endpoint itself stops answering.

Live views are explicitly bounded in-memory previews. Opening one requires
`manage_sources`; members can read the measurements of an open view. A live view
does not record anything. Accepted detector topics use only
`telemetry/<entity>/<reading>`; upstream topics can use arbitrary concrete MQTT
paths and JSON Pointer payload bindings.

### Monitors, pipelines and detectors

A monitor is named by its `monitor_id` everywhere; container names, container
ids and Docker states stay inside the installation. Members read everything
here; changes need `manage_monitors`.

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `GET` | `/monitors` | List monitors with their state, strategy and watched readings | Optional `active` |
| `POST` | `/monitors` | Start a form-configured monitor as a pipeline (HTTP 202) | Monitoring configuration body |
| `GET` | `/monitors/overview` | What the Monitoring page loads: every monitor, whether designs may be edited, and the selected monitor's pipeline state | Optional `selected_monitor_id` |
| `GET` | `/monitors/{monitor_id}` | One monitor with the configuration it was started with | Path: `monitor_id` |
| `PATCH` | `/monitors/{monitor_id}` | Rename a monitor | Body: `display_name` |
| `POST` | `/monitors/{monitor_id}/stop` | Stop a monitor and remove its workload; it stays listed as stopped | Path: `monitor_id` |
| `DELETE` | `/monitors/{monitor_id}` | Delete a monitor and its workload; 204, its alarms stay | Path: `monitor_id` |
| `GET` | `/monitors/{monitor_id}/pipeline` | The design a monitor runs, its current run, recent history and validation | Optional `selected_node_id` |
| `GET` | `/monitors/{monitor_id}/pipeline/history` | Earlier runs it replaced, newest first; the next page is the history of `next_monitor_id` | `limit` |
| `GET` | `/monitors/{monitor_id}/pipeline/timeline` | The run's lifecycle events, oldest first, and how it ended | Path: `monitor_id` |
| `GET` | `/monitors/{monitor_id}/pipeline/metadata` | Validation with the fields available at a node | `selected_node_id` |
| `GET` | `/monitors/{monitor_id}/pipeline/state` | The diagnostic snapshot the running monitor last reported | Path: `monitor_id` |
| `PUT` | `/monitors/{monitor_id}/pipeline/layout` | Store where its nodes sit on the canvas; the graph is unchanged | Body: layout |
| `GET` | `/pipelines` | Saved designs, paged | `limit`, `offset`, `query`, `archived` |
| `POST` | `/pipelines` | Save a new design as a draft | Body: `name`, `definition` |
| `POST` | `/pipelines/apply` | Save, publish and activate a design in one step (HTTP 202) | Body: `definition`, `bindings`, `display_name`, `idempotency_key`, optional `replace_monitor_id` and `shadow` |
| `POST` | `/pipelines/validate` | Check an unsaved design; with `selected_node_id` also its fields | Body: `definition` |
| `POST` | `/pipelines/edit` | Change a design in small edits without saving it; answers with the changed design and its check | Body: `edits`, optional `definition` and `layout` |
| `GET` | `/pipelines/{pipeline_id}` | One design with its draft, `version` and revisions | Path: `pipeline_id` |
| `PATCH` | `/pipelines/{pipeline_id}` | Rename, describe or archive a design | Body: `expected_version` and changes |
| `PUT` | `/pipelines/{pipeline_id}/draft` | Replace a design's draft graph and layout | Body: `expected_version`, `definition` |
| `POST` | `/pipelines/{pipeline_id}/validate` | Check a graph against a saved design | Body: `definition` |
| `GET` | `/pipelines/{pipeline_id}/revisions` | Published revisions, newest first | `limit`, `before` |
| `POST` | `/pipelines/{pipeline_id}/revisions` | Freeze the draft as a revision monitors can run | Body: `expected_version` |
| `GET` | `/pipelines/{pipeline_id}/revisions/{revision_id}` | One revision with its graph and fingerprint | Path ids |
| `GET` | `/pipelines/{pipeline_id}/revisions/{revision_id}/metadata` | Validation of a revision with the fields at a node | `selected_node_id` |
| `GET` | `/pipeline-components` | Components a design may use, each with its group, description and settings, and the starting templates | None |
| `GET` | `/pipeline-components/search` | Components that fit a purpose, the best fit first, a few lines each | Optional `query`, `kind`, `group`, `learning`, `limit` |
| `GET` | `/pipeline-components/{component_id}` | One component, with the JSON schema of its settings | None |
| `GET` | `/pipeline-blocks` | Every saved block, by name: `items`, each with `id`, `name`, `description`, `steps` and `created_at` | None |
| `POST` | `/pipeline-blocks` | Save a chain of steps as a block (HTTP 201). HTTP 409 when the name is taken or the library holds 100 blocks; 422 for a step a block cannot hold, such as a detector | Body: `name`, optional `description`, `steps` (1 to 16, each with `component` and optional `contract_version`, `params`, `label`) |
| `DELETE` | `/pipeline-blocks/{block_id}` | Delete a block (HTTP 204); designs keep the steps they copied from it | Path: `block_id` |
| `GET` | `/pipeline-proposals` | Proposals, the newest first, without their designs: `items`, each with `id`, `name`, `reason`, `author`, `author_kind`, `status`, `test_run_id`, `replace_monitor_id` and the decision | Query: optional `status` (`open`, `accepted`, `declined` or `withdrawn`) |
| `POST` | `/pipeline-proposals` | Hand a design to a member to decide on (HTTP 201). The design must check without errors. A `test_run_id` names a Dojo run that succeeded on this very design; a run that is missing, unfinished or of another design answers HTTP 422, and titles do not count as a difference. HTTP 409 while 50 proposals wait for a decision | Body: `name`, `reason`, `definition`, optional `layout`, `bindings`, `test_run_id`, `replace_monitor_id` |
| `GET` | `/pipeline-proposals/{proposal_id}` | One proposal with its `definition`, `layout` and `bindings` | Path: `proposal_id` |
| `POST` | `/pipeline-proposals/{proposal_id}/decision` | Accept or decline a proposal. Members only: a key cannot decide. Accepting starts nothing: the web app accepts a proposal once the start of its design has been requested. HTTP 409 once it is decided or withdrawn | Body: `status` (`accepted` or `declined`), optional `note` for the author |
| `POST` | `/pipeline-proposals/{proposal_id}/withdraw` | Take back a proposal that still waits. HTTP 403 for anyone but its author | Path: `proposal_id` |
| `GET` | `/forecast-models` | Models of the forecast service that pretrained forecaster steps use, each with its download `status`, `progress` and `error`; `service` is `not_deployed` or `unreachable` when there is none to list | None |
| `POST` | `/forecast-models/downloads` | Have the forecast service download a model's weights (HTTP 202); poll the list for progress | Body: `model` |
| `POST` | `/pipeline-activations` | Run a published revision as a monitor (HTTP 202) | Body: `revision_id`, `bindings`, `display_name`, `idempotency_key`, optional `replace_monitor_id` and `shadow` |
| `GET` | `/pipeline-activations/{activation_id}` | Progress of an activation: `phase`, `monitor_id`, issues | Path: `activation_id` |
| `POST` | `/pipeline-activations/{activation_id}/cancel` | Cancel an activation that has not finished | Path: `activation_id` |
| `GET` | `/detectors` | Detector models with family, cost and parameter schema | Optional `strategy` |
| `GET` | `/evidence` | Inference evidence of the observations that covered one reading | `reading_id`, `limit` |
| `GET` | `/evidence/chart` | Incrementally load chart evidence | `device_id`, or `reading_id` repeated for up to 200 readings, optional `monitor_id`, optional complete cursor, `limit` |

Evidence rows name their `monitor_id` and the `reading_ids` they covered;
`input_timestamps` is keyed by reading id. The chart cursor is the complete
tuple `after_created`, `after_timestamp`, `after_monitor_id`, and
`after_sequence_number`; if one is supplied, all four are required.

Every listed monitor, here and in `/monitors/overview`, carries `reading_ids`:
the catalogue readings it watches. Use it to answer "which monitors watch this
reading"; a reading removed from the catalogue drops out. A monitor's
`operational_status` names its inputs by reading id as well. How a reading is
recorded (its topic and ingress key) stays inside the backend. `active` is true
while the monitor should run and false once it is stopped.

`shadow` is true for a monitor started with `shadow` set. A shadow run learns
and scores as any monitor and raises no alarm: each alarm it would have raised
is an evidence row with `alarm` false and `muted` true, and no anomaly is
stored. The flag belongs to the start, not to the design, so the same design
runs either way. To take a shadow run live, start its design again with
`replace_monitor_id` and without `shadow`.

A monitor start body contains:

- required `display_name` and `reading_ids`: up to 100 distinct numeric readings
  that are recorded, all of one device or all of one broker without a device
- `monitoring`: the strategy configuration, including `strategy`
  (`static_baseline` or `adaptive_stream`), `model_type`, `model_params`, and
  the strategy's training, calibration, and alarm settings
- optional `performance_config`: `hold_intervals` (default 3),
  `minimum_hold_seconds` (default 30) and `future_tolerance_seconds`
  (default 5); see [Observation time and alignment](../user-guide/monitoring.md#observation-time-and-alignment)

Omitting `monitoring` selects the default static baseline. Other fields,
including the former top-level `mqtt_topics`, `strategy`, `model_type` and
`model_params`, and malformed configuration return HTTP 422.

TACTIC converts the configuration into its equivalent graph, binds one input
per reading and submits a pipeline activation, even while the visual workbench
is disabled. The graph's inputs carry the readings' catalogue labels. The HTTP
202 response carries `monitor_id`, `activation_id`, `phase` and `reading_ids`.
Poll `/pipeline-activations/{activation_id}` until its `phase` is `succeeded`,
`failed` or `cancelled`. A reading that is unknown, not numeric, not recorded or
of another device returns HTTP 422.

A run view (`/monitors/{monitor_id}/pipeline`) names its bound inputs by
`slot_id`, `reading_id` and `unit`. Its `binding_metadata` keeps the
`catalogue_revision` and `collection_revision` the run was bound against and,
per reading, the catalogue `label`, `unit`, `device_id`, `device_label`,
`broker_id`, `broker_label` and `collection_policy` at that time.

Use `/detectors` as the source for valid model names and parameter schemas.

`bindings` map each input slot of a design to a catalogue reading id. Repeating
an apply or activation with the same `idempotency_key` returns the first
activation instead of starting another; `replace_monitor_id` swaps out a running
monitor. Direct public graph launches are rejected so they cannot bypass
preflight, durable input reservations or run history.
Draft/layout conflicts return HTTP 409. Publishing does not activate a revision.
Run views survive deletion of the live monitor and expose retained input metadata,
terminal errors and compiler feature lineage. `/monitors/{monitor_id}/pipeline`
accepts an optional `selected_node_id` for member inspection even when authoring
is disabled. Each compiler report is
bounded to 512 KiB, omitting provenance and then whole unselected node tables
with a `metadata_budget` notice. Complete ordered names for the selected node
and its immediate parents remain available; inspect `features_complete` and
`provenance_complete` before interpreting missing metadata. Invalid oversized
definition echoes use `definition: null` and `definition_omitted: true`; bounded
errors expose `issues_truncated`. Internal MQTT overrides and runtime image pins
are rejected by public monitor creation.
See [pipeline architecture and rollout](../development/monitoring-pipelines.md).

#### Building a design in steps

A program or an agent that builds a design does not need the whole catalog or a
whole design at a time. `/pipeline-components/search` answers a purpose with a
few lines per component:

```http
GET /v1/pipeline-components/search?query=calm+noise&limit=3
```

```json
{
  "catalog_id": "68f7…",
  "total": 1,
  "components": [
    {
      "id": "prepare.smooth",
      "kind": "transform",
      "group": "prepare",
      "label": "Smooth",
      "description": "Average recent values to calm noise.",
      "learning": "none",
      "input_type": "features",
      "output_type": "features",
      "settings": ["apply_to", "result", "suffix", "method", "window_size"]
    }
  ]
}
```

A component fits when its name, its place in the catalog, its description or
one of its settings answers a word of the query. Words in a name count for more
than words in the help of a setting, and words few components answer for more
than common ones. `kind`, `group` and `learning` narrow the answer; without a
`query` every component they leave is listed, 10 at a time unless `limit` (up
to 100) says otherwise. Read `/pipeline-components/{component_id}` for what
each setting does.

`/pipelines/edit` makes small changes to a design the caller holds and stores
nothing. The body carries the `definition` and `layout` as they are (left out,
the design starts empty) and up to 100 `edits`, made in order:

| `op` | Fields | What it does |
| --- | --- | --- |
| `add_step` | `component`, optional `id`, `params`, `label`, `after`, `before` | Adds a step. With `after` and `before` it goes on the connection between the two; with one of them it is connected on that side |
| `remove_step` | `id`, optional `reconnect` | Removes a step and its connections. A transform with one input hands that input on, unless `reconnect` is false |
| `replace_step` | `id`, `component`, optional `params` | Makes a step another component; its id and connections stay |
| `set_params` | `id`, `params`, optional `unset` | Changes the named settings; those in `unset` return to their defaults |
| `set_label` | `id`, `label` | Titles a step; `null` takes the title away |
| `connect`, `disconnect` | `source`, `target` | Adds or removes a connection. A single input takes a new connection in place of the one it had |
| `add_input`, `remove_input` | `id`, optional `label`, `unit` | Declares a reading the design takes in, or takes one out |
| `set_settings` | `training_window_size`, `calibration_window_size`, `seed` | Changes those given |
| `add_note`, `remove_note` | `text`, optional `beside`; `id` | Puts a note above a step, or takes one off the canvas |

```json
{
  "definition": { "…": "the design as it was read" },
  "layout": { "…": "its layout" },
  "edits": [
    { "op": "add_step", "component": "prepare.smooth", "after": "input", "before": "detector", "params": { "window_size": 12 } },
    { "op": "add_note", "text": "The current is noisy at this rate.", "beside": "prepare_smooth_1" }
  ]
}
```

The answer has the changed `definition` with the defaults of every setting, the
`layout`, the ids the edits `added`, and the `report` that `/pipelines/validate`
would give for the result. Either every edit is made or none: an edit that
cannot be made, such as one naming a step the design does not have, answers
HTTP 422 with its place in the list, as in `Edit 2 (remove_step): The design
has no step 'gone'`. A design that results but would not run is no error; its
issues are in the report. New steps get a place on the canvas beside the step
they follow, and a step put on a connection gets room between the two it joins,
so the design reads well when a person opens it. Save the result with
`POST /pipelines` or `PUT /pipelines/{pipeline_id}/draft`.

### Favourites and alarms

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `GET` | `/favorites` | The current member's favourites, oldest first | Optional query: `kind` |
| `POST` | `/favorites` | Star a device, reading or monitor; an existing favourite is returned unchanged | Body: `kind`, `id` |
| `DELETE` | `/favorites` | Remove a favourite; 204 whether or not it existed | Query: `kind`, `id` |
| `GET` | `/alarms/count` | Count alarms | Optional query: `since` |
| `POST` | `/alarms/query` | Reporting: alarms of catalogue readings with catalogue names, a summary and per-reading counts; every member | Body: `reading_ids`, optional `reading_id`, `monitor_id`, `since`, `until`, `max_p_value`, `limit`, `before` |
| `GET` | `/alarms/{alarm_id}` | One anomaly and its exact retained detector evidence; every member | Path: event ID |
| `POST` | `/alarms/deletion-preview` | Freeze an exact deletion selection; requires `manage_alarms` | Body: either `alarm_ids` or `query`, with optional `exclude_ids`; returns token, count and expiry |
| `POST` | `/alarms/delete` | Delete a reviewed selection atomically; requires `manage_alarms` | Body: preview `token`; retries return the recorded deletion count |
| `GET` | `/alarms` | The newest alarms of a device, of readings, or of every reading | Query: `device_id` or `reading_id` (repeated, up to 200), optional `monitor_id`, `limit` |
| `POST` | `/alarms` | Record an alarm by hand and email the alert recipients; 201 with the alarm | Body: `reading_ids`, `timestamp`, `alarm_type`, `value`, optional `value_type` |
| `DELETE` | `/alarms/{alarm_id}` | Delete one alarm; 204, or 404 when there is none | Path: `alarm_id` |

A favourite's `kind` is `device` (a catalogue device id), `reading` (a catalogue
reading id) or `monitor` (a `monitor_id`). Ids are not checked against the
catalogue, so a favourite stays until the member removes it. A member keeps at
most 256; adding another answers 409.

An alarm names its catalogue `device_id` and `reading_ids` with their names in
`device_label` and `reading_labels`. A reading without a device has a null
`device_id`, and `device_label` names its broker. Readings the catalogue no
longer has are left out. `multivariate` marks an alarm a monitor raised over
several readings together. A manual alarm names readings of one device, or of
one broker without a device; several make it multivariate.

`POST /alarms/query` is a read, so members may call it although other `POST`
routes under `/alarms` need `manage_alarms`. An alarm is in the `reading_ids`
scope when one of its readings is. A multivariate alarm recorded without its
readings is only in scope when every reading of its device is. `summary` and
`readings` cover every match rather than the returned page; `readings` ignores
the narrowing filters so it can feed a reading picker. Pages are newest first;
pass `next` as `before`.

### Dojo

Datasets and runs for comparing detection approaches offline, apart from live
monitoring. A dataset is a frozen copy: retention and catalogue edits never
change it. A run replays one design over one dataset. Every route needs
`use_dojo`, reads included, because datasets are copies made for experiments.

| Method | Path | Purpose | Key inputs |
| --- | --- | --- | --- |
| `GET` | `/dojo/datasets` | List datasets, newest first | `limit`, `offset` |
| `POST` | `/dojo/datasets/csv` | Create a dataset from a CSV request body (`text/csv`, at most 100 MB) | Query: `name`, `layout` (`wide` or `long`), optional `timestamp_column`, `series_column`, `value_column`, `delimiter`, `filename`, `description` |
| `POST` | `/dojo/datasets/history` | Copy recorded readings for one window into a dataset | Body: `name`, `reading_ids`, `end`, optional `start` (omitted: from the first stored value) |
| `GET` | `/dojo/datasets/{dataset_id}` | One dataset with its series | Path: `dataset_id` |
| `PATCH` | `/dojo/datasets/{dataset_id}` | Rename or describe a dataset | Body: `name`, `description` |
| `DELETE` | `/dojo/datasets/{dataset_id}` | Delete a dataset and its values; 204 | Path: `dataset_id` |
| `GET` | `/dojo/datasets/{dataset_id}/series/{series_id}/points` | Values of one series in time order | `after`, `limit` (at most 10,000); continue with `next_after` |
| `GET` | `/dojo/datasets/{dataset_id}/labels` | The dataset's labels, ordered by start | Path: `dataset_id` |
| `GET` | `/dojo/datasets/{dataset_id}/label-suggestions` | Alarms live monitors recorded on the readings the dataset was copied from, inside its span, grouped into episodes as candidate labels; nothing is stored, and an upload gets none | Optional `gap_seconds` (default 600): alarms closer together form one suggestion |
| `POST` | `/dojo/datasets/{dataset_id}/labels` | Mark a known problem as an interval | Body: `start_at`, `end_at`, optional `note` |
| `POST` | `/dojo/datasets/{dataset_id}/labels/batch` | Add up to 200 labels in one write: all of them, or none when one overlaps or the dataset would hold more than 500; 201 with the new labels | Body: `labels`, each with `start_at`, `end_at`, optional `note` |
| `PATCH` | `/dojo/datasets/{dataset_id}/labels/{label_id}` | Move a label or change its note | Body: `start_at`, `end_at`, `note` |
| `DELETE` | `/dojo/datasets/{dataset_id}/labels/{label_id}` | Delete a label; 204 | Path: `dataset_id`, `label_id` |
| `GET` | `/dojo/datasets/{dataset_id}/comparison` | Up to six finished runs of the dataset, scored against its labels | `run_ids`, repeated once per run |
| `GET` | `/dojo/runs` | List runs, newest first | Optional `dataset_id`, `status`; `limit`, `offset` |
| `POST` | `/dojo/runs` | Queue a replay of one design over one dataset | Body: `dataset_id`, `definition`, `bindings` (slot id to series id), optional `name`, `alignment`, `compare_calibration` |
| `GET` | `/dojo/runs/{run_id}` | One run with its design, progress and counts | Path: `run_id` |
| `POST` | `/dojo/runs/{run_id}/cancel` | Cancel a waiting or running run | Path: `run_id` |
| `POST` | `/dojo/runs/{run_id}/promote` | Save the run's design as a library template; 201. Also needs `manage_monitors` | Body: `name`, optional `description` |
| `DELETE` | `/dojo/runs/{run_id}` | Delete a finished run and its results; 204 | Path: `run_id` |
| `GET` | `/dojo/runs/{run_id}/metrics` | Event metrics of a finished run against the dataset's labels | Path: `run_id` |
| `GET` | `/dojo/runs/{run_id}/calibration` | The calibration methods a finished run also tried on its scores, each scored against the labels; 409 for a run started without `compare_calibration` | Path: `run_id` |
| `GET` | `/dojo/runs/{run_id}/results` | Detector results in order | `after`, `limit` (at most 10,000), optional `alarm`; continue with `next_after` |
| `GET` | `/dojo/runs/{run_id}/outline` | The results summed up over equal stretches of time: per stretch the number of results and alarms and the lowest and highest score and threshold | `buckets` (300 by default, at most 2,000) |
| `GET` | `/dojo/runs/{run_id}/steps` | What 12 to 23 observations of an ended run looked like at every step: the values that went in and came out, or why the step gave none | Path: `run_id` |

A wide CSV has one timestamp column (the first unless `timestamp_column`
names another) and one series per remaining column; a long CSV has one value
per row in `series`, `timestamp` and `value` columns. Timestamps are ISO 8601
or Unix epoch seconds or milliseconds, UTC without a zone. The delimiter is
detected from the header; with `;` or tab a decimal comma is accepted. A
dataset holds at most 64 series and 5,000,000 values, and two values for the
same series and instant are rejected.

A run is compiled and bound when it is created, so a design error is refused
at once. The Dojo worker, a service on the RADAR image, then replays the bound
series in time order through the same alignment and detector code as a live
monitor. The clock is the data's own time, so `alignment.hold_intervals` and
`alignment.minimum_hold_seconds` mean what the live monitor settings mean. A
static baseline's fitting is awaited instead of discarding observations, so
the same run gives the same results again. Each worker replica executes one
run at a time; at most 20 runs wait or run at once. A run's `stats` count
observations that produced no result, by reason.

A label marks a known problem as the interval from `start_at` to `end_at`.
Labels of one dataset may touch but not overlap and must overlap the dataset's
time span; a dataset holds at most 500. Metrics treat each label as one event
and are computed when read, from the stored results and the current labels,
so editing a label re-scores every finished run without a replay. A label is
`detected` when the run alarmed inside it, ends included, with
`delay_seconds` from its start to the first alarm; `missed` when the run
scored it without alarming; and `unscored` when the run had no scores during
it, for example while the detector was still learning. `detection_rate`
divides detected labels by scored ones. Each alarm onset outside every label
is one false alarm, so an alarm held over many results counts once, and one
that starts inside a label and outlasts it does not count.
`false_alarms_per_day` divides them by `evaluated_seconds`, the scored time
outside the labels. Only runs with status `succeeded` have metrics.

A run created with `compare_calibration` also tries the other calibration
methods on its own detector scores: the fixed split and the 15 methods that
adapt, without the run's own. Each gets the calibration window and then every
scored observation, as the run's own calibration step does, and nothing a
method decides reaches the run. All aim at one alarm rate, `alpha`, and alarm
after `consecutive` scores in a row above their boundary. A run whose step
adapts gives its own `alpha` and the `consecutive` of its detection rule; a
fixed split gives the share its quantile leaves above the threshold, at least
one in n + 1 for a calibration window of n, and `consecutive` 1. The other
methods run with their default settings. A design that alarms on a conformal
martingale has no boundary on scores and is refused with 422.
`GET /dojo/runs/{run_id}/calibration` lists the run's own step first
(`own`), then the others, each with the event metrics above counted from the
first result the methods judged, and `alarm_share`, the share of judged
results it would have alarmed on. A method that raised an error on the scores
stops there and says why in `failed`; the run itself carries on. Its counts
are of what it found until then, and `alarm_share`, `detection_rate` and
`false_alarms_per_day` are null, because they would be over results it never
judged.

Promoting a run copies its compiled design into the pipeline library as a new
template, the same as `POST /pipelines`, so pipeline authoring must
be enabled and the member needs `manage_monitors`. The answer names the new
`pipeline_id` and lists each input slot with the series it was bound to. For a
series copied from recorded history, `reading_id` is the catalogue reading it
came from, the live input to bind when the template starts a monitor; an
uploaded series has none. The template has no published revision yet.

#### Import and metrics bounds

CSV imports accept up to 65 columns per record (a timestamp and 64 series),
64 Ki characters per logical record, and 256 characters per series name. These
limits also apply to quoted multiline records and unused columns in long CSVs.
Ordinary wide and long CSV uploads retain their existing overall upload limits.

Run, run-comparison, and calibration-comparison metrics cache their bounded
aggregates until label intervals change. An uncached calculation uses a shared
database slot and returns a retryable conflict when another calculation holds
it. Calculations have a 30-second request deadline and a 25-second database
statement deadline. These protections use built-in defaults and need no new
environment variables.

### MCP server for agents

The gateway is also a [Model Context Protocol](https://modelcontextprotocol.io)
server. An agent connects to `/v1/mcp`, behind the dashboard
`https://<dashboard>/api/v1/mcp`, and sends its key as
`Authorization: Bearer <key>` with every request. Only a key connects: without
one the answer is 401, and a member's token gets 403.

The transport is streamable HTTP without a session. Each `POST` gets one JSON
answer, nothing is streamed and `GET` answers 405, so a proxy has nothing to
hold open and any replica answers any request.

| Tool | What the agent does with it | Operation behind it |
| --- | --- | --- |
| `list_devices`, `list_readings` | Finds what can be monitored | `GET /devices`, `GET /devices/{device_id}/readings` |
| `profile_reading` | Learns what a reading looks like before it chooses steps | `GET /readings/{reading_id}/profile` |
| `search_components`, `get_component` | Finds steps by purpose and reads one with its settings | `GET /pipeline-components/search`, `GET /pipeline-components/{component_id}` |
| `list_designs`, `get_design` | Reads a design to start from: a starter, a saved template, the design of a running monitor or a proposal | `GET /pipeline-components`, `/pipelines`, `/monitors`, `/monitors/{monitor_id}/pipeline`, `/pipeline-proposals/{proposal_id}` |
| `edit_design`, `validate_design` | Changes a design in small edits and checks it | `POST /pipelines/edit`, `POST /pipelines/validate` |
| `test_design`, `get_test` | Replays a design over the last days of its readings and reads how many alarms it would have raised | `POST /dojo/datasets/history`, `POST /dojo/runs`, `GET /dojo/runs/{run_id}` and its `/metrics` |
| `propose_design`, `list_proposals`, `withdraw_proposal` | Hands a design to a member and learns what they decided | `/pipeline-proposals` |
| `start_monitor`, `get_start` | Starts a monitor without a member's decision, in shadow with `shadow` set | `POST /pipelines/apply`, `GET /pipeline-activations/{activation_id}` |

`start_monitor` and `get_start` exist only for a key whose `starts` is `shadow`
or `live`; another key neither sees nor can call them. A key with `shadow`
passes `shadow` to `start_monitor`, and a start without it is refused in the
route's words. The grant is read with every request, so
it holds from the next one.

A tool is a call to the operations beside it, made with the agent's key. The
rules on this page therefore hold for a tool as they are: what a key may call,
the rate limits, and the texts of errors. A refusal comes back as the result of
the tool with `isError` set and the `detail` of the operation as its text, such
as `Edit 2 (remove_step): The design has no step 'gone'`, so the agent can
change its call and try again. Arguments a tool does not know are refused, not
ignored.

A design passes between the tools as the agent received it: `definition` and
`layout` from `get_design` or `edit_design` go into the next tool unchanged.
`test_design` copies the last `days` (7 unless given, up to 30) of the bound
readings into a Dojo dataset and queues a run on it; with the `dataset_id` of
an earlier test the design runs on the same copy, so two results compare.
`get_test` and `get_start` wait up to `wait_seconds` (20 unless given, at most
45) for the run or the start to finish before they answer. `start_monitor`
names each start with an idempotency key of its own unless the agent gives
one, and cannot replace a running monitor: that stays a proposal with
`replace_monitor_id`.

### Gateway health

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Gateway liveness; this route is outside the `/v1` prefix |

## TACTIC API — `/api/v1`

All business routes require `X-Off-Key-Service-Key`; collection, membership and
role routes additionally validate the end-user bearer token and its permissions. TACTIC is private.
Health and readiness remain available without this service credential.

The gateway is the only caller. Its routes above forward to these, under the
names the installation uses internally: a catalogue is the
`system`, recording is `collection`, a broker is a `connection`, a live view is
a `lease` and a monitor is a `service`.

### Members, sessions and roles

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/members/me` | Profile of the signed-in member with role and permissions |
| `GET` | `/members` | List organization members |
| `POST` | `/members/invitations` | Invite a member or resend the invitation |
| `PATCH` | `/members/{user_id}` | Change a member's role, active state or both |
| `DELETE` | `/members/{user_id}` | Permanently remove a disabled member; 204 |
| `POST` | `/members/accept-invitation` | Activate an invited account with its token and a password |
| `POST` | `/members/request-password-reset` | Send reset mail when the account exists |
| `POST` | `/members/reset-password` | Set a new password with the token from the reset mail |
| `POST` | `/members/sessions` | Create the remembered session behind the gateway's session cookie |
| `POST` | `/members/sessions/refresh` | Rotate a remembered session's token |
| `POST` | `/members/sessions/revoke` | Revoke a remembered session |
| `POST` | `/members/sessions/revoke-access` | Revoke the supplied bearer token |
| `GET` | `/roles` | Roles with their permissions and member counts |
| `POST` | `/roles` | Create a role |
| `PATCH` | `/roles/{role_id}` | Rename a role or replace its permissions |
| `DELETE` | `/roles/{role_id}` | Delete a role no member holds; 204 |
| `GET` | `/agents/me` | The agent a key belongs to; the gateway asks this for every request that carries a key |
| `GET` | `/agents` | Agents that hold a key |
| `POST` | `/agents` | Create an agent and its key, returned this once |
| `PATCH` | `/agents/{agent_id}` | Allow or forbid the key to start monitoring services |
| `DELETE` | `/agents/{agent_id}` | Revoke the key; 204 |

### Catalogue, recording and live views

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/system` | Saved catalogue document, revision and how each reading is recorded |
| `PUT` | `/system` | Save structural catalogue changes at an expected revision |
| `GET` | `/system/revisions` | Saved catalogue revisions |
| `POST` | `/system/connections/check` | One MQTT CONNECT to a saved broker, then disconnect; never subscribes. For an HTTP broker, one `GET` |
| `POST` | `/system/connections/reconnect` | Retry a recorded broker now instead of waiting for its backoff |
| `PUT` | `/system/collection` | Apply confirmed recording policies |
| `POST` | `/system/collection/preview` | Review a recording change and the monitors it affects |
| `POST` | `/system/collection/status` | Recording state and latest values of the given readings |
| `GET` | `/system/health` | Recording diagnosis with the raw ingress and collector reports |
| `GET` | `/system/storage` | Storage size and managed retention status |
| `GET` | `/system/live` | Open live views: brokers, readings and samples after a sequence number |
| `POST` | `/system/live/leases` | Open a bounded live view of readings |
| `PUT` | `/system/live/leases/{lease_id}` | Keep a live view open, optionally with other readings |
| `DELETE` | `/system/live/leases/{lease_id}` | Close a live view; 204 |

### Pipelines and monitor runs

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/monitors/workspace` | What the Monitoring page loads: every monitor, whether designs may be edited, and the selected monitor's pipeline state |
| `GET` | `/monitors/{service_id}/pipeline` | The design a monitor runs, its current run, recent history and validation |
| `GET` | `/monitors/{service_id}/pipeline-history` | Earlier runs the monitor replaced, newest first |
| `GET` | `/monitors/{service_id}/pipeline-timeline` | The run's lifecycle events, oldest first, and how it ended |
| `GET` | `/monitors/{service_id}/pipeline-metadata` | Validation with the fields available at a node |
| `GET` | `/monitors/{service_id}/pipeline-state` | The diagnostic snapshot the running monitor last reported |
| `PUT` | `/monitors/{service_id}/pipeline-layout` | Store where the nodes sit on the canvas; the graph is unchanged |
| `GET` | `/monitors/pipelines` | Saved designs, paged |
| `POST` | `/monitors/pipelines` | Save a new design as a draft |
| `POST` | `/monitors/pipelines/apply` | Save, publish and activate a design in one step |
| `POST` | `/monitors/pipelines/validate` | Check an unsaved design without creating a library record |
| `POST` | `/monitors/pipelines/edit` | Change a design in small edits; nothing is stored |
| `GET` | `/monitors/pipelines/catalog` | Components a design may use, each with its group, description and settings, and the starting templates |
| `GET` | `/monitors/pipelines/catalog/search` | Components that fit a purpose, a few lines each |
| `GET` | `/monitors/pipelines/catalog/components/{component_id}` | One component, with the JSON schema of its settings |
| `GET` | `/monitors/pipelines/forecast-models` | The forecast service's models and their download state, asked with TACTIC's token |
| `POST` | `/monitors/pipelines/forecast-models/downloads` | Have the forecast service download a model's weights |
| `GET` | `/monitors/pipelines/{pipeline_id}` | One design with its draft, version and revisions |
| `PATCH` | `/monitors/pipelines/{pipeline_id}` | Rename, describe or archive a design |
| `PUT` | `/monitors/pipelines/{pipeline_id}/draft` | Replace a design's draft graph and layout |
| `POST` | `/monitors/pipelines/{pipeline_id}/validate` | Check a graph against a saved design |
| `GET` | `/monitors/pipelines/{pipeline_id}/revisions` | Published revisions, newest first |
| `POST` | `/monitors/pipelines/{pipeline_id}/revisions` | Freeze the draft as a revision monitors can run |
| `GET` | `/monitors/pipelines/{pipeline_id}/revisions/{revision_id}` | One revision with its graph and fingerprint |
| `GET` | `/monitors/pipelines/{pipeline_id}/revisions/{revision_id}/metadata` | Validation of a revision with the fields at a node |
| `GET` | `/monitors/pipeline-blocks` | Every saved block, by name |
| `POST` | `/monitors/pipeline-blocks` | Save a chain of steps as a block |
| `DELETE` | `/monitors/pipeline-blocks/{block_id}` | Delete a block; designs keep the steps they copied from it |
| `GET` | `/monitors/pipeline-proposals` | Proposals, the newest first, without their designs |
| `POST` | `/monitors/pipeline-proposals` | Hand a design to a member to decide on |
| `GET` | `/monitors/pipeline-proposals/{proposal_id}` | One proposal with its design |
| `POST` | `/monitors/pipeline-proposals/{proposal_id}/decision` | A member accepts or declines a proposal |
| `POST` | `/monitors/pipeline-proposals/{proposal_id}/withdraw` | The author takes back a proposal that still waits |
| `POST` | `/monitors/pipeline-activations` | Run a published revision as a monitor |
| `GET` | `/monitors/pipeline-activations/{activation_id}` | Progress of an activation: phase, monitor and issues |
| `DELETE` | `/monitors/pipeline-activations/{activation_id}` | Cancel an activation that has not finished |

### Data adapter

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/data/devices` | Catalogue devices with recording status |
| `GET` | `/data/devices/{device_id}/readings` | Catalogue readings of one device |
| `GET` | `/data/readings/{stream_id}/measurements` | Measurements of a catalogue reading |
| `GET` | `/data/readings/{stream_id}/measurements/buckets` | Downsampled measurements of a catalogue reading |
| `GET` | `/data/readings/{stream_id}/profile` | What a catalogue reading looks like over its last days |
| `GET` | `/data/evidence` | Evidence of a catalogue reading |
| `GET` | `/data/evidence/chart` | Chart evidence of a catalogue device or of catalogue readings |
| `POST` | `/data/auth/login` | Internal authentication check |
| `GET` | `/data/users/{user_id}/favorites` | List favourites |
| `POST` | `/data/users/{user_id}/favorites` | Add a favourite |
| `DELETE` | `/data/users/{user_id}/favorites` | Remove a favourite named by query `kind` and `id` |
| `GET` | `/data/alarms` | Alarms of a catalogue device or of catalogue readings |
| `POST` | `/data/alarms/query` | Reporting query by catalogue reading |
| `GET` | `/data/alarms/{alarm_id}` | One anomaly with its exact retained evidence |
| `POST` | `/data/alarms/deletion-preview` | Freeze matching event identities for ten minutes |
| `POST` | `/data/alarms/delete` | Commit a reviewed selection with an idempotent token |
| `GET` | `/data/alarms/count` | Count alarms |
| `POST` | `/data/alarms` | Record an alarm about catalogue readings |
| `DELETE` | `/data/alarms/{alarm_id}` | Delete an alarm |

### Dojo

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/dojo/datasets` | List datasets |
| `POST` | `/dojo/datasets/csv` | Import a CSV body |
| `POST` | `/dojo/datasets/history` | Copy recorded readings |
| `GET` | `/dojo/datasets/{dataset_id}` | Read a dataset |
| `PATCH` | `/dojo/datasets/{dataset_id}` | Rename or describe a dataset |
| `DELETE` | `/dojo/datasets/{dataset_id}` | Delete a dataset |
| `GET` | `/dojo/datasets/{dataset_id}/series/{series_id}/points` | Page through one series |
| `GET` | `/dojo/datasets/{dataset_id}/labels` | List a dataset's labels |
| `GET` | `/dojo/datasets/{dataset_id}/label-suggestions` | Suggest labels from recorded alarms |
| `POST` | `/dojo/datasets/{dataset_id}/labels` | Add a label, refusing overlaps |
| `POST` | `/dojo/datasets/{dataset_id}/labels/batch` | Add several labels as one write |
| `PATCH` | `/dojo/datasets/{dataset_id}/labels/{label_id}` | Move or annotate a label |
| `DELETE` | `/dojo/datasets/{dataset_id}/labels/{label_id}` | Delete a label |
| `GET` | `/dojo/datasets/{dataset_id}/comparison` | Score runs of one dataset side by side |
| `GET` | `/dojo/runs` | List runs |
| `POST` | `/dojo/runs` | Compile, bind and queue a run |
| `GET` | `/dojo/runs/{run_id}` | Read a run |
| `POST` | `/dojo/runs/{run_id}/cancel` | Cancel a run |
| `POST` | `/dojo/runs/{run_id}/promote` | Save a run's design as a template |
| `DELETE` | `/dojo/runs/{run_id}` | Delete a finished run |
| `GET` | `/dojo/runs/{run_id}/metrics` | Score a finished run against the labels |
| `GET` | `/dojo/runs/{run_id}/calibration` | Score the calibration methods a run also tried |
| `GET` | `/dojo/runs/{run_id}/results` | Page through a run's results |
| `GET` | `/dojo/runs/{run_id}/outline` | Sum a run's results up over equal stretches of time |
| `GET` | `/dojo/runs/{run_id}/steps` | Read the values a few observations had at every step |

### RADAR orchestration

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/orchestration/radar/services/` | List services |
| `POST` | `/orchestration/radar/services/start/` | Start a form-configured monitor as a pipeline activation |
| `GET` | `/orchestration/radar/services/{service_id}` | Get one service with its configuration |
| `POST` | `/orchestration/radar/services/{service_id}/stop` | Stop a service and remove its workload |
| `PATCH` | `/orchestration/radar/services/{service_id}/label` | Rename a service |
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

- The Gateway API family remains `/favorites`. The dashboard's Favorites filter uses `/?state=favorites`; the old `/favourites` frontend route redirects there.
- Removed sync and preprocessor-discovery routes must not be used by new clients.

## Related pages

- [Architecture](../development/architecture.md)
- [Data model](data-model.md)
- [Testing and debugging](../development/testing-debugging.md)
- [Web app](../user-guide/web-app.md)
