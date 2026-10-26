# Environment variables

This page is the canonical runtime-configuration reference for the tracked environment templates.

## When to use this page

Use this page when configuring local Compose or production deployments.

## Configuration files

| File | Purpose | Commit policy |
| --- | --- | --- |
| `.env.example` | Tracked local-development template | Commit-safe placeholders only |
| `.env` | Local Compose and application configuration | Never commit |
| `infra/ansible/inventories/prod/group_vars/all/vault.yml.example` | Production secret names | Placeholders only |
| GitHub `production` environment | Encrypted vault, inventory and CI access | Private secrets |

Create the local files from the templates:

=== "Bash"

    ```bash
    cp .env.example .env
    ```

=== "PowerShell"

    ```powershell
    Copy-Item .env.example .env
    ```

!!! important
    Secret-bearing values are intentionally not reproduced in this documentation. Variable names and validation requirements are safe to document; runtime values belong in ignored files or a production secret store.

Production values are rendered by Ansible from the encrypted vault. See
[GitHub setup](../operations/github-setup.md) for secret names and access.

## Secret handling rules

Treat the values of these variables as secrets:

| Variable | Requirement |
| --- | --- |
| `JWT_SECRET` | Unique signing secret, at least 32 characters; do not reuse between environments |
| `INTERNAL_API_SECRET` | Unique gateway-to-TACTIC credential, at least 32 characters |
| `EMAIL_PASSWORD` | SMTP credential when authenticated delivery is enabled |
| `POSTGRES_PASSWORD` | Unique database credential outside disposable local development |
| `EMQX_DASHBOARD_PASSWORD` | Unique EMQX administrative credential |
| `EMQX_NODE_COOKIE` | Shared only by trusted nodes in the same EMQX cluster |
| `MQTT_APIKEY` | Required only when MQTT authentication is enabled |

Generate secrets locally and put the output directly into the intended secret store or ignored environment file:

```bash
openssl rand -hex 32
```

Do not paste generated output into issues, logs, commits, screenshots, or documentation.

## Application and HTTP

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `APP_NAME` | Required, no default; `.env.example` sets `aberration` | API title shown by the gateway; non-empty string |
| `ENVIRONMENT` | `development` | Runtime environment label |
| `DEBUG` | `false` | Debug-mode toggle; keep disabled in production |
| `BACKEND_PORT` | `8000` | Gateway host port |
| `FRONTEND_PORT` | `5173` | Frontend host port |
| `FRONTEND_BASE_URL` | `http://localhost:5173` | Base URL used in emailed links |
| `CORS_ALLOWED_ORIGINS` | Local frontend and Gateway origins | Valid JSON array of allowed origins |
| `API_PROXY_TARGET` | `http://api-gateway:8000` | Development only: where the Vite dev server proxies `/api`; use `http://localhost:8000` for host-run Vite. The old name `VITE_API_URL` is still read. Built images always call `/api` on their own origin |

## Authentication

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `JWT_SECRET` | Not documented | Access-token signing secret |
| `INTERNAL_API_SECRET` | Not documented | Required gateway-to-TACTIC credential |
| `ALGORITHM` | `HS256` | Must match the backend JWT implementation |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Positive access-token lifetime |
| `SUPERUSER_MAIL` | Local placeholder address | Mailbox for the operator-generated first administrator invitation |

## Email

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `EMAIL_USERNAME` | Local Mailpit user | SMTP username when credentials are enabled |
| `EMAIL_PASSWORD` | Not documented | SMTP password when credentials are enabled |
| `EMAIL_FROM` | Local placeholder address | Valid sender address |
| `SMTP_SERVER` | `mailpit` | Reachable SMTP host |
| `SMTP_PORT` | `1025` | SMTP port, `1–65535` |
| `MAIL_STARTTLS` | `false` | Enable STARTTLS when required by the provider |
| `MAIL_SSL_TLS` | `false` | Enable implicit TLS when required by the provider |
| `USE_CREDENTIALS` | `false` | Enables SMTP username/password authentication |
| `VALIDATE_CERTS` | `false` | Enable certificate validation outside local Mailpit use |
| `ANOMALY_ALERT_RECIPIENTS` | Local administrator address | Comma-separated recipient addresses |

## PostgreSQL and TimescaleDB

Every backend service reads these with the same rules and no code defaults; the
defaults below come from `.env.example`. Managed RADAR workers receive the
resulting URL as `RADAR_DATABASE_URL` from TACTIC.

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `POSTGRES_USER` | `postgres` | Database user |
| `POSTGRES_PASSWORD` | Not documented | Database credential |
| `POSTGRES_DB` | `off_key` | Database name |
| `POSTGRES_HOST` | `timescaledb` | Host reachable from backend containers |
| `POSTGRES_PORT` | `5432` | Database port, `1–65535` |

## MQTT proxy

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `MQTT_BROKER_HOST` | `emqx-main` | Internal EMQX host |
| `MQTT_BROKER_PORT` | `1883` | Internal EMQX port |
| `MQTT_USE_TLS` | `false` | TLS to the internal EMQX broker |
| `MQTT_USE_AUTH` | `false` | EMQX authentication toggle |
| `MQTT_TELEMETRY_ENABLED` | `true` | Persist collected telemetry; fixed to `true` in the local Compose file |

When `MQTT_USE_AUTH=true`, provide the supported `MQTT_USERNAME` and `MQTT_APIKEY` runtime variables through an ignored file or secret store.

The proxy retains transient database failures in bounded batches and applies
backpressure until persistence recovers. Recognized permanent record errors
(PostgreSQL data exceptions, NOT NULL/check violations, and oversized index rows)
trigger individual writes to isolate invalid records. Rejected records are logged
as `db_writer.record_rejected`, counted in `total_records_rejected`, and discarded;
they are not stored for replay. Valid records continue through the same
charger/telemetry transaction. Connection, schema, permission, foreign-key, and
unknown errors remain eligible for retry.

## EMQX

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `EMQX_DASHBOARD_USERNAME` | `admin` | Dashboard login name |
| `EMQX_DASHBOARD_PASSWORD` | Not documented | Dashboard credential |
| `EMQX_NODE_COOKIE` | Not documented | Node/cluster cookie; all nodes in one cluster must agree |

## TACTIC-managed RADAR workloads

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `TACTIC_DOCKER_API_URL` | `http://socket-proxy` | Restricted Docker API proxy URL |
| `TACTIC_DOCKER_API_PORT` | `2375` | Docker API proxy port |
| `TACTIC_DOCKER_MAX_CONCURRENT_CALLS` | `5` | Concurrent Docker calls per client: one shared by requests and the activation supervisor, one for the reconciliation sweep |
| `TACTIC_RADAR_DEFAULT_MQTT_BROKER_HOST` | `emqx-main` | Broker supplied to managed RADAR workloads; TACTIC's collection publisher uses it too, so it must be the broker mqtt-proxy subscribes on (`MQTT_BROKER_HOST`) |
| `TACTIC_RADAR_DEFAULT_MQTT_BROKER_PORT` | `1883` | Managed RADAR and collection publisher broker port |
| `TACTIC_RADAR_DEFAULT_MQTT_USE_TLS` | `false` | Managed RADAR and collection publisher TLS |
| `TACTIC_RADAR_DEFAULT_MQTT_USE_AUTH` | `false` | Managed RADAR and collection publisher authentication; the publisher falls back to `TACTIC_RADAR_DEFAULT_MQTT_USERNAME` when `SYSTEM_COLLECTION_MQTT_USERNAME` is empty |
| `TACTIC_RADAR_WORKLOAD_LIFECYCLE` | `ephemeral` | `ephemeral` or `persistent` |
| `TACTIC_PIPELINE_AUTHORING_ENABLED` | `true` | Enables the visual Create workbench, new designs, publication and activations. Set `false` to hide the workbench; the setup forms still start monitors as pipelines, and existing graph execution, inspection, stopping and release recovery remain available. |
| `TACTIC_PIPELINE_PREFLIGHT_TIMEOUT_SECONDS` | `90` | Constructor preflight deadline, 5–300 seconds. Jobs have no broker/database credentials or subscriptions. |
| `TACTIC_PIPELINE_HEARTBEAT_TIMEOUT_SECONDS` | `120` | Successor heartbeat deadline after creation, 10–600 seconds. |
| `TACTIC_PIPELINE_MAX_CONCURRENT_PREFLIGHTS`, `TACTIC_PIPELINE_MAX_CONCURRENT_TRANSITIONS` | `2`, `8` | Activation concurrency bounds; see [Monitoring pipelines](../development/monitoring-pipelines.md) |
| `TACTIC_RADAR_DEFAULT_MEMORY_LIMIT_MB`, `TACTIC_RADAR_DEFAULT_MAX_QUEUE_SIZE`, `TACTIC_RADAR_DEFAULT_MAX_PAYLOAD_BYTES` | `384`, `256`, `65536` | Managed worker budgets; see [RADAR deployment capacity](../operations/radar-capacity.md) |
| `TACTIC_RADAR_MAX_ACTIVE_MONITORS` | `20` | Monitor count limit; see [RADAR deployment capacity](../operations/radar-capacity.md) |
| `TACTIC_DOCKER_DEFAULT_MEMORY_LIMIT`, `TACTIC_DOCKER_DEFAULT_CPU_LIMIT` | `512m`, `0.5` | Swarm service limits for managed workers; see [RADAR deployment capacity](../operations/radar-capacity.md) |
| `RADAR_CHECKPOINT_SECRET` | Development value in `.env.example`; a Swarm secret in production | Signs runtime checkpoints; see [RADAR recovery](../operations/radar-recovery.md) |
| `TACTIC_SERVICE_HOST` | `middleware_tactic` (Compose sets `tactic-middleware`) | Where the API gateway reaches TACTIC; read only by the gateway |
| `TACTIC_SERVICE_PORT` | `8000` | TACTIC port the API gateway calls; read only by the gateway |
| `DEMO_MODE` | `false` | Public read-only demo: signed-out visitors reach only listed reads; see [Public demo](../operations/public-demo.md) |
| `DEMO_VIEWER_EMAIL`, `DEMO_VIEWER_PASSWORD` | Empty | The ordinary member account guests browse as; required with `DEMO_MODE`. Administrators are refused. TACTIC reads the same pair when `bootstrap_demo_viewer` creates or refreshes that member during a demo deployment |
| `DEMO_GUEST_REQUESTS_PER_MINUTE` | `240` | Requests per minute and visitor address for signed-out demo guests |

## RADAR workloads

TACTIC sets these on each workload it launches.

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `RADAR_MQTT_BROKER_HOST` | `emqx-main` | RADAR broker |
| `RADAR_MQTT_BROKER_PORT` | `1883` | Broker port |
| `RADAR_MQTT_USE_TLS` | `false` | MQTT TLS toggle |
| `RADAR_MQTT_USE_AUTH` | `false` | MQTT authentication toggle |
| `RADAR_SUBSCRIPTION_TOPICS` | Set by TACTIC | Concrete topics from the monitor's selected readings (wildcards are rejected) |
| `RADAR_MONITORING_CONFIG` | Set by TACTIC | Strategy settings derived from the pipeline; when supplied, they must match the graph |
| `RADAR_PIPELINE_CONFIG` | Required | Version-1 canonical bound execution JSON, emitted by activation. Every monitor runs a pipeline; RADAR does not start without one. Limited to 96 KiB serialized. |
| `RADAR_FATAL_PERSIST_RETRY_SECONDS` | `5` | Retry interval while a quarantined managed graph waits to persist its failed-run admission fence. Must be greater than zero and at most 30 seconds. No further graph calls or checkpoint exports occur. |
| `RADAR_RATE_LIMIT_PER_MINUTE` | `0` | Aggregate observation limit across the monitor's topics; `0` disables throttling. Positive limits discard excess inputs and permanently flag the monitor's coverage as degraded. Managed workloads use `TACTIC_RADAR_DEFAULT_RATE_LIMIT_PER_MINUTE`, also defaulting to `0`. |
| `RADAR_MAX_QUEUE_SIZE` | `256` | Maximum admitted messages waiting for the serial processor, bounded before the network thread schedules asyncio work. |
| `RADAR_MAX_PAYLOAD_BYTES` | `65536` | Maximum admitted payload size. Larger observations are discarded and counted as coverage gaps. The default queue holds at most 16 MiB of payload bytes plus object overhead. Enforce broker packet limits as well: the MQTT library receives a packet before admission. |
| `RADAR_OBSERVATION_MAX_AGE_SECONDS` | `30` | Maximum observation age at processing/emission, independently of when its MQTT packet arrived. |
| `RADAR_OBSERVATION_FUTURE_TOLERANCE_SECONDS` | `5` | Maximum permitted observation time ahead of the worker clock. |
| `RADAR_ALIGNMENT_MAX_SKEW_SECONDS` | `5` | Maximum time spread between observations in one aligned vector. |

The former strategy variables (`RADAR_MONITORING_STRATEGY`, `RADAR_MODEL_TYPE`,
`RADAR_MODEL_PARAMS`, `RADAR_STATIC_BASELINE_CONFIG` and
`RADAR_ADAPTIVE_STREAM_CONFIG`) are no longer read.

## Internal services, retention, and logging

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `SYNC_API_HOST` | `0.0.0.0` | DB Sync bind address |
| `SYNC_API_PORT` | `8009` | DB Sync internal API port |
| `TELEMETRY_RETENTION_DAYS` | `14` | Retention for telemetry and monitoring evidence; integer `1–365`. DB Sync reconciles existing policies at startup; restart/redeploy it after changing this value. |
| `LOG_LEVEL` | `INFO` | Standard log-level token |
| `LOG_FORMAT` | `simple` | `simple` writes text lines that end with any `extra=` context as `key=value` pairs; `json` writes one object per line with that context under `extra` |
| `LOG_REDACT_PII` | `true` | Keep enabled where logs may contain user data |
| `LOG_PII_DEBUG_UNMASK` | `false` | Never enable in shared or production environments |
| `ENABLE_REQUEST_LOGGING` | `true` | HTTP request logging toggle (gateway only) |
| `ENABLE_PERFORMANCE_LOGGING` | `true` | Performance logging toggle (gateway only) |
| `LOG_CORRELATION_HEADER` | `X-Correlation-ID` | Request header that carries the correlation ID; the gateway forwards it to TACTIC and both echo it in responses. Inbound IDs other than 1 to 128 letters, digits or `._:-` are replaced |

## Production images and collection ingress

Production resolves every application image to the digest published from the exact
tested main commit. Images are recorded in the verified server release; local
`.env` image overrides do not control production.

| Variable | Default / requirement | Purpose |
| --- | --- | --- |
| `SYSTEM_COLLECTION_ENABLED` | `true` | Run persistent generic collection independently of previews |
| `SYSTEM_LIVE_ENABLED` | `false` in service defaults | Permit temporary in-memory previews |
| `SYSTEM_LIVE_ALLOWED_HOSTS` | Operator configuration | Allowed generic upstream brokers |
| `SYSTEM_LIVE_DATA_SOURCE` | `broker` | `simulated` replaces upstream brokers with generated preview data |
| `SYSTEM_LIVE_CONNECT_TIMEOUT_SECONDS` | `15` | Upstream broker connection deadline for previews |
| `SYSTEM_COLLECTION_MQTT_USERNAME`, `SYSTEM_COLLECTION_MQTT_API_KEY`, `SYSTEM_COLLECTION_MQTT_CA_FILE` | Empty locally; private TACTIC secrets in production | Internal EMQX publisher credentials and CA; see [Collection](../operations/system-collection.md) |
| `SYSTEM_LIVE_CREDENTIALS` | Private JSON mapping | Credential reference to MQTT username/password |
| `SYSTEM_LIVE_SOCKS_PROXIES` | Private JSON mapping | Exact broker host to SOCKS route |
| `AMBIBOX_INGRESS_ENABLED` | `false` in service defaults; enabled in local/prod deployment | Allow reuse of operator-provisioned private broker access |
| `AMBIBOX_ALLOWED_HOST_SUFFIXES` | `[".ts.net"]` | Broker host allowlist suffixes |
| `AMBIBOX_ALLOWED_HOSTS` | `["source-broker"]` in local Compose | Explicit additional allowed hosts |
| `AMBIBOX_EMQX_API_URL` | `http://emqx-main:18083/api/v5` | Private EMQX management endpoint |
| `AMBIBOX_EMQX_API_KEY`, `AMBIBOX_EMQX_API_SECRET` | Operator secrets | Access used to retire generated v1 ingress resources |
| `AMBIBOX_GOST_API_URL` | `http://mqtt-tailscale-bridge:18080` | Private GOST management endpoint |
| `AMBIBOX_GOST_USERNAME`, `AMBIBOX_GOST_PASSWORD` | Operator credentials | Access used to retire generated v1 forwarder resources |
| `AMBIBOX_MQTT_USERNAME`, `AMBIBOX_MQTT_PASSWORD` | Existing vendor credentials | Shared upstream broker access |
| `AMBIBOX_SOCKS_SERVER` | `tailscale-ambibox:1055` in production | Existing vendor tailnet SOCKS endpoint |

See [Deployment modes](../operations/deployment-modes.md) and [Collection](../operations/system-collection.md) for deployment and catalog setup.

## Troubleshooting by variable group

| Symptom | Likely variables | First action |
| --- | --- | --- |
| Frontend loads but API calls fail | `API_PROXY_TARGET`, `BACKEND_PORT`, `CORS_ALLOWED_ORIGINS` | Align the URL with host/container reachability and CORS |
| Verification/reset links are wrong | `FRONTEND_BASE_URL` | Set the externally reachable frontend URL |
| SMTP delivery fails | `SMTP_*`, `EMAIL_*`, TLS and credential toggles | Match the provider transport and authentication requirements |
| No source telemetry | Catalog selection, `MQTT_BROKER_*`, MQTT auth/TLS | Verify reachability, topic shape, and credentials |
| Managed workload cannot start | `TACTIC_DOCKER_API_*`, `TACTIC_RADAR_DEFAULT_*` | Check TACTIC readiness, proxy access, broker, and image |
| Vendor broker has no traffic | `AMBIBOX_INGRESS_ENABLED`, `AMBIBOX_SOCKS_SERVER` | Verify persisted vendor identity, tailnet reachability, and upstream host |

## RADAR configuration files

Managed worker resource budgets, queue bounds, reservations and the monitor count
limit are described in [RADAR deployment capacity](../operations/radar-capacity.md).

`RADAR_CONFIG_FILE` optionally selects a dotenv file loaded once, before RADAR
settings and components are constructed. File values override environment values.
Restart the workload after changing configuration; running services do not watch
or reload the file.

## Related pages

- [Getting started](../getting-started.md)
- [Developer setup](../development/setup.md)
- [Deployment modes](../operations/deployment-modes.md)
