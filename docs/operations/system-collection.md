# Catalogue and collection

**Sources** opens the generic catalogue editor. Verified administrators can save
brokers, entities, concrete MQTT topics, payload fields and catalogue groups;
members can inspect them. The installation-wide database is authoritative.
Export/import uses only `aberration-system` schema version 1. Credentials, host
allowlists, TLS requirements and private network routes stay with the operator.

## Data path

```mermaid
flowchart LR
  B[Configured MQTT brokers] --> I[Selected TACTIC subscriptions]
  I --> E[Internal EMQX envelopes]
  E --> C[Bounded opt-in collector]
  C --> H[Numeric history and latest state]
  C --> R[Accepted telemetry topics]
  R --> M[Monitoring services]
```

Upstream topics are arbitrary concrete MQTT paths. Several readings may extract
different JSON Pointer fields from one topic. Catalogue IDs identify definitions;
saved runtime bindings identify their entity and reading in storage. Rename a
definition without changing its ID to retain its binding and monitor association.
Accepted numeric observations use `telemetry/<entity>/<reading>` and the existing
`{value, timestamp}` payload. The collector never subscribes to its own output.

Persistent subscriptions run independently of views and login sessions. Temporary
**Connect** previews use bounded memory and do not enable recording. Opening a
recorded reading loads existing history, then follows new stored observations.

## Explicit collection

New readings start **Off**, including readings imported with enabled policies in
their file. Existing policies survive edits by stable reading identity. Changes
to admitted inputs or cadence require stopping affected active monitors before
applying; their settings remain available for restart.

- **Off:** no persistent subscription, storage or accepted output for the input.
- **Original rate:** fresh numeric observations enter a bounded queue. Overload
  drops new observations and increments the drop counter. This is best-effort
  telemetry rather than a durable lossless transport.
- **Sample:** emit the latest pending observation when its interval becomes due,
  retaining its observation timestamp. Quiet streams are not filled or repeated.
- **Boolean, text and identifier:** persist latest state only; original-rate
  state updates are coalesced to at most one per second. These do not enter numeric
  history or the detector feed.
- **Retained snapshots:** update latest state without becoming fresh history or
  detector input. Only fresh admitted observations update entity contact status.

The initial definition limits are 128 brokers, 2,048 entities, 4,096 readings,
128 groups and 1 MiB. The original-rate queue defaults to 10,000 observations.
Decode, coalescing and overload counters are visible in diagnostics. Database
backpressure retains bounded pending batches. Process loss can lose memory queues;
accepted MQTT output is not transactionally coupled to a database commit.

## Applying configuration

Saves use an expected revision and a PostgreSQL advisory lock. Concurrent edits
receive a conflict. Monitor starts use the same lock to prevent changes racing
with input claims. Monitor stop intent commits before workload removal; completed
stops remain durable even if a later stop or catalogue save fails.

The collector pauses admission, drains pending database and MQTT output, installs
the new subscriptions and reports `prepared`. TACTIC then establishes selected
broker subscriptions for that configuration generation. After matching ingress
is applied, the collector enables admission. Failure remains visible and retries;
an empty selection is healthy idle. Old queued generations cannot enter a new
mapping. Turning an input Off preserves previously recorded history.

## Upgrade from the previous runtime

Use the production release's packaged migration workflow; do not execute SQL
files individually or reset the database. Application writers stop before schema
changes, and the release captures monitor restart configuration.

Migration `005_generic_runtime.sql` converts saved catalogue and monitor topic
configuration once. Stable bindings, names, explicit policies, accounts,
favourites and model settings survive. Only old sensor measurements (`telemetry`)
and latest-value caches (`collection_state`) are cleared. Catalogue/revision
archives, monitoring evidence and other application records remain. Later releases
retain samples recorded after the upgrade.

The generic runtime is the sole operational model. Retired catalogue APIs,
provider-specific imports and old accepted topics are not supported. Before
starting generic ingress, the controller removes only its generated v1
`offkey_ambibox_` EMQX/GOST resources. Operator-authored routes remain intact.

## Operator access and retention

`SYSTEM_COLLECTION_ENABLED` controls persistent ingress independently of
`SYSTEM_LIVE_ENABLED`. Generic broker allowlists, credential references and optional
SOCKS routes are private operator configuration. Existing Ambibox operator access
can still supply its configured credentials, registered tailnet route and TLS
requirement to allowed hosts; the application model is independent of that
provider. Catalogue exports contain no credentials.

Internal publishing uses the configured EMQX TLS/authentication defaults and the
private `SYSTEM_COLLECTION_MQTT_USERNAME`, `SYSTEM_COLLECTION_MQTT_API_KEY` and
`SYSTEM_COLLECTION_MQTT_CA_FILE`. Production mounts its publisher credential and
CA as TACTIC secrets. Settings reports ingress/collector revisions and diagnostics.

Storage diagnostics remain under **Settings**. `TELEMETRY_RETENTION_DAYS` (1–365,
default 14) controls managed TimescaleDB retention for telemetry and monitoring
evidence. DB sync reconciles those policies on startup without changing other
jobs. Shortening retention makes old chunks eligible for scheduled cleanup; it
does not affect accounts, catalogues or anomalies. Increasing retention cannot
recover data already removed.

For local MQTT examples and private catalogue simulation, see
[Local deployment](../development/local-deployment.md).
