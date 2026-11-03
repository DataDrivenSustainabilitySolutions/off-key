# Worker observability

Loki and Grafana run on one explicitly selected worker (`observability_data_node`,
production: `DDSS-2`). Alloy, a GET-only Docker log proxy, and a tiny log canary run
once per active worker. No observability task is eligible for a manager.

The manager must retain headroom for Swarm coordination, SSH and existing ingress.
Do not drain or restart it to move these services: that can affect other workloads.

## Capacity and storage

The validated policy gives Loki 1 GiB / 1 CPU, Grafana 512 MiB / 0.5 CPU, each
Alloy 256 MiB / 0.5 CPU, each proxy 64 MiB / 0.25 CPU, and each canary 16 MiB /
0.05 CPU. Every service has a memory and CPU reservation. A data worker must be
ready, active and have at least 3 GiB actually available RAM before deployment.

The storage role creates only `/var/lib/offkey-observability/storage.ext4` and
mounts it at `/srv/offkey-observability`. The filesystem has a fixed 20 GiB budget,
shared by Loki and Grafana. The image is sparse, so 20 GiB is its maximum growth,
not an immediate 20 GiB allocation. Creation requires an additional 10 GiB host
disk reserve. Existing images are never reformatted or silently resized.

Its own systemd unit starts before Docker without making Docker depend on it.
Failure to mount therefore does not prevent unrelated applications from starting.
The underlying mountpoint is inaccessible to the explicit Loki/Grafana UIDs, so
those services fail closed instead of filling the host disk if storage is absent.
No Docker daemon restart or global daemon configuration change is required.

Loki retains seven days, throttles ingestion, limits query concurrency, and limits
WAL replay to 256 MiB under its 1 GiB container limit. Writes stop at 85% usage of
the bounded filesystem, leaving recovery/compaction space. The data is node-local:
changing `observability_data_node` requires a stopped, verified data transfer,
not just a placement change. Keep the old copy until the new worker is verified.

## Collection and access

Discovery selects this stack's namespace. Legacy dynamic RADAR workers are
selected by both their immutable runtime image and the stack's private EMQX
network, because older workers lack namespace labels. Unrelated applications and
collector self-logs are excluded before tailing. Run UUIDs remain in log records;
the service label for RADAR is stable to avoid one indexed stream per run.

Only a per-node proxy mounts the host Docker socket. Alloy connects to its local
Unix socket through a node-local volume, avoiding cross-node load balancing.
The proxy denies writes, exec, filesystem archives, secret and administration
APIs. Permitted container metadata is still sensitive; it is not a separate tenant
security boundary. There are no proxy TCP listeners or published monitoring ports.
Grafana retains the existing oauth2-proxy/Traefik gate and internal network.

Saved read positions are not a durable delivery queue. Transient delivery failures
retry within bounded resources; after retries are exhausted, logs may be lost.
The canary emits a non-secret record every 30 seconds. Verification queries Loki
for a fresh canary from every eligible worker, proving discovery, tailing, proxy,
delivery and querying rather than merely accepting a running container.

## Independent deployment and recovery

Application deployment never submits the monitoring services, waits for them,
quiesces them as database writers, or rolls back because they fail. After an
application release is verified and its maintenance fence is closed, deployment
reconciles monitoring separately. A monitoring failure is reported independently.

```sh
make -C infra deploy-observability-prod
make -C infra check-observability-prod
make -C infra pause-observability-prod
```

The standalone playbook reads the running RADAR image for scoped discovery and
renders only non-secret monitoring configuration. It runs no application image
update, migration, bootstrap email or database maintenance. Pause removes only
labelled global monitoring services and scales labelled Loki/Grafana to zero;
all data is retained. Redeploy recreates the node agents.

For a failed deployment, inspect only the component's task errors and bounded
logs. Never dump environment maps, credentials or private application logs into
CI, a public issue or a commit. Check the selected node, memory headroom, storage
unit and filesystem identity before retrying. Use an independent availability
monitor for notification if this whole worker or the manager is unreachable;
the local Grafana instance cannot provide an out-of-band notification guarantee.

## Validation

The infrastructure suite renders the real Ansible/Compose configuration. The
separate CI rehearsal runs a disposable three-node Swarm in isolated Docker
engines, with a 1 CPU / 1 GiB manager. It checks worker-only placement, fresh logs
from both workers, legacy RADAR discovery, unrelated-log exclusion, Docker API
denials, retained logs after a Loki restart, application convergence while Loki
is stopped, dashboard updates without collector/Loki restarts, and pause without
changing the unrelated application fixture.

The offline engines use imported immutable image content IDs, checked against
the pinned public images. Docker archives do not preserve registry manifest
references; this avoids registry access inside the lab without changing image
contents. Integration evidence contains booleans and capacity metadata only.
