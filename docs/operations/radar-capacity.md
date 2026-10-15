# RADAR deployment capacity

Each managed monitor is one Docker workload with a bounded database pool. Default
budgets are:

| Setting | Default |
| --- | --- |
| Docker memory hard limit and Swarm reservation | 512 MiB |
| Docker CPU limit and Swarm reservation | 0.5 CPU |
| RADAR internal RSS alert/cleanup target | 384 MiB |
| MQTT queue capacity | 256 messages |
| Maximum MQTT payload | 65,536 bytes |
| Concurrent active or pending monitors | 20 |
| PostgreSQL pool per worker | At most 2 connections, no overflow |

Swarm reserves CPU and memory before scheduling each worker. Reservations default
to the configured hard limits. Explicit smaller positive reservations are allowed
but permit more workloads to share a node; size these from measured concurrent
workloads. Invalid, zero, nonfinite, or malformed resource quantities fail
configuration validation. Reservations cannot exceed limits, and RADAR's internal
target must remain below the Docker memory limit.

`TACTIC_RADAR_MAX_ACTIVE_MONITORS` limits the fleet under the same database lock
that serializes sensor claims. Pending creations and unresolved Docker outcomes
consume a slot. Retrying the same accepted monitor does not consume another slot.
The limit does not represent an automatic measurement of available fleet capacity.
Set it to fit both eligible Swarm nodes and PostgreSQL connection headroom after
accounting for API/controller pools, migrations, and operational access. Twenty
monitors can consume forty database connections. The second worker connection
allows a health heartbeat to report a blocked evidence transaction.

Configure limits with `TACTIC_DOCKER_DEFAULT_MEMORY_LIMIT` and
`TACTIC_DOCKER_DEFAULT_CPU_LIMIT`. Override reservations with the corresponding
`TACTIC_DOCKER_DEFAULT_MEMORY_RESERVATION` and
`TACTIC_DOCKER_DEFAULT_CPU_RESERVATION` variables. Unset/empty reservation settings
inherit the limits. Configure the internal target and ingress bounds with
`TACTIC_RADAR_DEFAULT_MEMORY_LIMIT_MB`, `TACTIC_RADAR_DEFAULT_MAX_QUEUE_SIZE`, and
`TACTIC_RADAR_DEFAULT_MAX_PAYLOAD_BYTES`. These are forwarded to every worker.

At default ingress limits, queued payload bytes are bounded to 16 MiB. Configuration
rejects a raw payload capacity that reaches the internal memory target. This bound
excludes Python object overhead, topics, decoded data, model state, evidence queues,
training/calibration buffers, and checkpoint serialization copies. The internal
target triggers observation/cleanup; Docker enforces the actual memory limit.

Profile representative sensor counts, data rates, detector parameters, full fitting,
and checkpoint peaks before admitting a deployment workload. The accepted model
parameter/window ranges do not establish that every configuration fits the default
worker budget. A large model can exhaust its memory limit even with a small queue.
Increase the measured worker budget and its reservation together, or reduce model
size, before increasing the fleet limit. No static calibration-memory estimate is
used to promise safety for arbitrary models.

The development container fallback has cgroup CPU/memory limits and a memory
reservation hint; production requires Swarm for scheduler admission.
