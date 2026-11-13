# RADAR deployment capacity

Monitors run in the RADAR worker pool: the `mqtt-radar` service. TACTIC writes
each monitor and preflight job as a row of `radar_workloads`, pinned to the
`TACTIC_RADAR_IMAGE` runtime. Each pool replica running that image leases rows
up to its capacity and runs each one as a child process with a bounded database
pool. Default budgets are:

| Setting | Default |
| --- | --- |
| Pool replicas (`RADAR_POOL_REPLICAS`) | 1 locally, 2 in production |
| Children per replica (`RADAR_POOL_CAPACITY`) | 8 |
| Memory per child before the pool kills it (`TACTIC_POOL_MEMORY_LIMIT`) | 512 MiB |
| Memory limit of one replica in Swarm (`RADAR_POOL_MEMORY_LIMIT`) | 4 GiB |
| RADAR internal RSS alert/cleanup target | 384 MiB |
| MQTT queue capacity | 256 messages |
| Maximum MQTT payload | 65,536 bytes |
| Concurrent active or pending monitors | 20 |
| PostgreSQL pool per monitor | At most 2 connections, no overflow |

Replicas times capacity bounds how many monitors run at once. A row no replica
has room for stays pending, and the activation reports that no replica has room
for it yet. Size `RADAR_POOL_MEMORY_LIMIT` to at least capacity times the child
limit, plus the replica's own small footprint; otherwise the kernel kills the
replica before the pool's own per-child limit applies.

The pool checks each child's resident memory and kills a child past its limit
with SIGKILL. The crash is recorded with exit code 137 and a hint naming the
memory limit. A crashed monitor restarts with backoff until it crashes
`RADAR_POOL_MAX_RESTARTS` times within the restart window; it is then left
failed with "Crashed N times; not restarted".

`TACTIC_RADAR_MAX_ACTIVE_MONITORS` limits the fleet under the same database lock
that serializes sensor claims. Pending rows consume a slot. Retrying the same
accepted monitor does not consume another slot. Set the limit to fit both the
pool's capacity and PostgreSQL connection headroom after accounting for
API/controller pools, the pool replicas themselves, migrations, and operational
access. Twenty monitors can consume forty database connections. The second
worker connection allows a health heartbeat to report a blocked evidence
transaction.

Configure the internal target and ingress bounds with
`TACTIC_RADAR_DEFAULT_MEMORY_LIMIT_MB`, `TACTIC_RADAR_DEFAULT_MAX_QUEUE_SIZE`, and
`TACTIC_RADAR_DEFAULT_MAX_PAYLOAD_BYTES`. These are forwarded to every worker.
The internal target must stay below the child memory limit.

At default ingress limits, queued payload bytes are bounded to 16 MiB. Configuration
rejects a raw payload capacity that reaches the internal memory target. This bound
excludes Python object overhead, topics, decoded data, model state, evidence queues,
training/calibration buffers, and checkpoint serialization copies. The internal
target triggers observation/cleanup; the pool enforces the actual memory limit.

Profile representative sensor counts, data rates, detector parameters, full fitting,
and checkpoint peaks before admitting a deployment workload. The accepted model
parameter/window ranges do not establish that every configuration fits the default
worker budget. A large model can exhaust its memory limit even with a small queue.
Increase the child limit and the replica limit together, or reduce model size,
before increasing the fleet limit. No static calibration-memory estimate is used
to promise safety for arbitrary models.

## Leases and failover

A replica renews its leases every poll. A replica that cannot renew for half the
lease (`RADAR_POOL_LEASE_SECONDS`, default 30 s) kills all its children, so a row
never runs twice: once the lease expires another replica claims it. A replica
that stops cleanly stops its children and releases their rows, so another
replica takes them at once. Deleting a monitor sets the row's intent to stop;
the row is removed only after the pool confirms the child has ended, and the
lease keeps being renewed until then.
