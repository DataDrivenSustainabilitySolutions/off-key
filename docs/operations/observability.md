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

## Dashboard navigation and signal meaning

The **Aberration** folder contains five provisioned dashboards, ordered along the
investigation path. The operations overview is the default home dashboard unless
a user has selected their own home. Existing overview and log URLs remain valid.

| Dashboard | Use it for |
| --- | --- |
| [01 · Operations overview](https://grafana.aberration.app/d/aberration-system-overview) | Canary delivery, previously observed silent workers, application errors and RADAR failure signals; expand logging volume to investigate noisy services. |
| [02 · Collection & persistence](https://grafana.aberration.app/d/aberration-collection) | Source/ingress interruptions, MQTT transport, writer retries, slow-write warnings and PostgreSQL/schema errors. |
| [03 · RADAR & Dojo](https://grafana.aberration.app/d/aberration-radar) | Detector transitions, failures and coverage gaps; expand healthy runtime samples or offline replay outcomes. Filter by a run or monitor reference. |
| [04 · HTTP & access](https://grafana.aberration.app/d/aberration-access) | Recorded HTTP exceptions, throttled access warnings and notification delivery failures. |
| [05 · Log investigation](https://grafana.aberration.app/d/aberration-logs) | Original records with service, worker, level and case-insensitive literal text filters. Counts and logs share the same scope. |

Stack and worker selections and the time range travel with dashboard navigation.
Service and worker choices come from scoped Loki labels; no production hostname
or stack name is baked into the queries. Expandable diagnostic rows defer their
queries until opened. Only the overview refreshes automatically (once per minute).
Other dashboards preserve the investigation window until refreshed. Metric panels
have a one-minute minimum interval and 180-point budget; logs return the newest
200 records. Use a narrower time range or Explore for further records.

The layout follows Grafana's guidance on [hierarchical dashboards, scoped variables
and versioned definitions](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/).
The panels deliberately distinguish observations from application state:

- A canary proves delivery from a worker. It does not prove any application is
  healthy. The silent-worker count compares the preceding 24 hours with the last
  two minutes; drained workers may appear, and never-seen workers cannot appear.
- An event count is a count of emitted records, not unique incidents, failed runs
  or lost readings. A zero is shown only when the relevant source emitted some
  logs; an absent source remains **No observations**. Historical delivery counts
  are evaluated at the selected end time.
- Production disables successful HTTP request and performance logs. The access
  dashboard therefore makes no request-rate, overall-latency or availability claim.
  Access warnings are throttled; suppressed counts are reported by a subsequent
  warning and do not include occurrences still waiting to be reported.
- RADAR emits healthy summaries about once per minute. Throughput and process RSS
  use the last sample within two minutes per monitor; missing or degraded monitors
  remain gaps. Lifecycle transitions do not describe the current desired state.
  Dojo failures include the domain-failure event logged at INFO.
- Writer success detail is DEBUG-only. Slow-write warnings describe a selected
  subset, not the latency distribution of all writes. Loki has no node CPU,
  filesystem utilization, current collection counters or queue-depth exporter.
  Use the application for monitor state and collection readiness, and the storage
  runbook for capacity checks.

JSON parsing reads only the required fields; application `event=...` pairs live
inside `message`. Run IDs, correlation IDs, arbitrary paths and full messages are
not added to indexed labels. Literal search handles quotes, backticks, Unicode and
regex punctuation without treating the input as LogQL. See [Loki's log-derived
metric semantics](https://grafana.com/docs/loki/latest/query/metric_queries/).

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

## Dashboard source and deployment

Edit the small Python definitions under `infra/grafana/`, then regenerate the
checked-in JSON used by Swarm:

```sh
python3 infra/scripts/build_grafana_dashboards.py
python3 infra/scripts/build_grafana_dashboards.py --check
make check-infra
```

The deployment copies and content-hashes every dashboard and mounts each as an
immutable Swarm config. Both a normal production release and the standalone
observability playbook reconcile these files. The topology check rejects stale
or missing config names/mounts even if the Grafana container is healthy. Changing
only a dashboard replaces Grafana's task; Alloy and Loki do not restart.

The file provider polls every 30 seconds and prevents UI saves. Dashboard UIDs
are stable, and Grafana's database and preferences remain on its bounded data
volume. Source JSON recreates the suite after a fresh installation; UI changes
are not the deployment source. `disableDeletion: true` protects dashboards if a
source temporarily disappears. Retiring a dashboard needs an explicit cleanup;
simply removing its source does not delete the retained database copy. This uses
Grafana's [file provisioning and overwrite behavior](https://grafana.com/docs/grafana/latest/administration/provisioning/#dashboards).

After deployment, open the overview, confirm the expected active workers, and
follow each dashboard link. Quiet error panels are expected. Start a monitor or
Dojo replay only through normal application workflows if runtime samples are
needed; do not manufacture production failures to populate a chart. Dashboard
provisioning does not configure alert receivers or change authentication.

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

The suite also checks generated JSON against its sources and ensures every
dashboard is copied, hashed and mounted. In the disposable Loki instance, all
panel queries are parsed and evaluated against synthetic records shaped like the
application logs. Assertions cover tenant isolation, missing-versus-zero data,
silent canaries, JSON message parsing, INFO-level Dojo failures, latest healthy
samples, and literal searches containing quotes and other special characters.

The offline engines use imported immutable image content IDs, checked against
the pinned public images. Docker archives do not preserve registry manifest
references; this avoids registry access inside the lab without changing image
contents. Integration evidence contains booleans and capacity metadata only.
