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
| `APP_NAME` | `off-key` | Application display name; non-empty string |
| `ENVIRONMENT` | `development` | Runtime environment label |
| `DEBUG` | `false` | Debug-mode toggle; keep disabled in production |
| `BACKEND_PORT` | `8000` | Gateway host port |
| `FRONTEND_PORT` | `5173` | Frontend host port |
| `FRONTEND_BASE_URL` | `http://localhost:5173` | Base URL used in emailed links |
| `CORS_ALLOWED_ORIGINS` | Local frontend and Gateway origins | Valid JSON array of allowed origins |
| `VITE_API_URL` | `http://api-gateway:8000` | API URL reachable from the frontend runtime; use `http://localhost:8000` for host-run Vite |

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

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `POSTGRES_USER` | `postgres` | Database user |
| `POSTGRES_PASSWORD` | Not documented | Database credential |
| `POSTGRES_DB` | `off_key` | Database name |
| `POSTGRES_HOST` | `timescaledb` | Host reachable from backend containers |
| `POSTGRES_PORT` | `5432` | Database port, `1–65535` |

## MQTT source and proxy

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `MQTT_BROKER_HOST` | `emqx-main` | Internal EMQX host |
| `MQTT_BROKER_PORT` | `1883` | Source MQTT port |
| `MQTT_USE_TLS` | `false` | TLS for the source client |
| `MQTT_USE_AUTH` | `false` | Source-broker authentication toggle |
| `MQTT_TELEMETRY_ENABLED` | `true` | Persist parsed source telemetry |

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
| `TACTIC_RADAR_DEFAULT_MQTT_BROKER_HOST` | `emqx-main` | Broker supplied to managed RADAR workloads |
| `TACTIC_RADAR_DEFAULT_MQTT_BROKER_PORT` | `1883` | Managed RADAR broker port |
| `TACTIC_RADAR_DEFAULT_MQTT_USE_TLS` | `false` | Managed RADAR TLS default |
| `TACTIC_RADAR_DEFAULT_MQTT_USE_AUTH` | `false` | Managed RADAR authentication default |
| `TACTIC_RADAR_WORKLOAD_LIFECYCLE` | `ephemeral` | `ephemeral` or `persistent` |
| `TACTIC_SERVICE_HOST` | `tactic-middleware` | Internal service-discovery host |
| `TACTIC_SERVICE_PORT` | `8000` | Internal service-discovery port |

## Standalone RADAR profile

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `RADAR_MQTT_BROKER_HOST` | `emqx-main` | Standalone RADAR broker |
| `RADAR_MQTT_BROKER_PORT` | `1883` | Broker port |
| `RADAR_MQTT_USE_TLS` | `false` | MQTT TLS toggle |
| `RADAR_MQTT_USE_AUTH` | `false` | MQTT authentication toggle |
| `RADAR_SUBSCRIPTION_TOPICS` | Simulator sine sensor topic | Comma-separated concrete topics for one charger |
| `RADAR_MONITORING_CONFIG` | Default static baseline | JSON strategy configuration containing `strategy`, model parameters, and training/calibration settings |

TACTIC-managed workloads receive `RADAR_MONITORING_CONFIG` as their single
monitoring configuration. Standalone RADAR still accepts the legacy
`RADAR_MONITORING_STRATEGY`, `RADAR_MODEL_TYPE`, `RADAR_MODEL_PARAMS`,
`RADAR_STATIC_BASELINE_CONFIG`, and `RADAR_ADAPTIVE_STREAM_CONFIG` variables when
the canonical variable is absent. Do not mix the formats; conflicting settings
prevent startup.

## Internal services, retention, and logging

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `SYNC_HOSTNAME` | `db-sync` | DB Sync service hostname |
| `SYNC_API_HOST` | `0.0.0.0` | DB Sync bind address |
| `SYNC_API_PORT` | `8009` | DB Sync internal API port |
| `TELEMETRY_RETENTION_DAYS` | `14` | Retention for telemetry and monitoring evidence; integer `1–365`. DB Sync reconciles existing policies at startup; restart/redeploy it after changing this value. |
| `LOG_LEVEL` | `INFO` | Standard log-level token |
| `LOG_FORMAT` | `simple` | Supported log output format |
| `LOG_REDACT_PII` | `true` | Keep enabled where logs may contain user data |
| `LOG_PII_DEBUG_UNMASK` | `false` | Never enable in shared or production environments |
| `ENABLE_REQUEST_LOGGING` | `true` | HTTP request logging toggle |
| `ENABLE_PERFORMANCE_LOGGING` | `true` | Performance logging toggle |

## Production images and collection ingress

Production resolves every application image to the digest published from the exact
tested main commit. Images are recorded in the verified server release; local
`.env` image overrides do not control production.

| Variable | Default / requirement | Purpose |
| --- | --- | --- |
| `AMBIBOX_INGRESS_ENABLED` | `false` in service defaults; enabled in local/prod deployment | Run the catalog controller |
| `AMBIBOX_ALLOWED_HOST_SUFFIXES` | `[".ts.net"]` | Broker host allowlist suffixes |
| `AMBIBOX_ALLOWED_HOSTS` | `["source-broker"]` in local Compose | Explicit additional allowed hosts |
| `AMBIBOX_EMQX_API_URL` | `http://emqx-main:18083/api/v5` | Private EMQX management endpoint |
| `AMBIBOX_EMQX_API_KEY`, `AMBIBOX_EMQX_API_SECRET` | Operator secrets | EMQX controller access |
| `AMBIBOX_GOST_API_URL` | `http://mqtt-tailscale-bridge:18080` | Private GOST management endpoint |
| `AMBIBOX_GOST_USERNAME`, `AMBIBOX_GOST_PASSWORD` | Operator credentials | Forwarder management access |
| `AMBIBOX_MQTT_USERNAME`, `AMBIBOX_MQTT_PASSWORD` | Existing vendor credentials | Shared upstream broker access |
| `AMBIBOX_SOCKS_SERVER` | `tailscale-ambibox:1055` in production | Existing vendor tailnet SOCKS endpoint |

See [Deployment modes](../operations/deployment-modes.md) and [AmbiBox collection](../operations/ambibox-collection.md) for deployment and catalog setup.

## Troubleshooting by variable group

| Symptom | Likely variables | First action |
| --- | --- | --- |
| Frontend loads but API calls fail | `VITE_API_URL`, `BACKEND_PORT`, `CORS_ALLOWED_ORIGINS` | Align the URL with host/container reachability and CORS |
| Verification/reset links are wrong | `FRONTEND_BASE_URL` | Set the externally reachable frontend URL |
| SMTP delivery fails | `SMTP_*`, `EMAIL_*`, TLS and credential toggles | Match the provider transport and authentication requirements |
| No source telemetry | Catalog selection, `MQTT_BROKER_*`, MQTT auth/TLS | Verify reachability, topic shape, and credentials |
| Managed workload cannot start | `TACTIC_DOCKER_API_*`, `TACTIC_RADAR_DEFAULT_*` | Check TACTIC readiness, proxy access, broker, and image |
| Swarm ingress has no traffic | `INGRESS_*` | Verify persisted state, tailnet reachability, and upstream host |

## Related pages

- [Getting started](../getting-started.md)
- [Developer setup](../development/setup.md)
- [Deployment modes](../operations/deployment-modes.md)

## RADAR configuration files

`RADAR_CONFIG_FILE` optionally selects a dotenv file loaded once, before RADAR
settings and components are constructed. File values override environment values.
Restart the workload after changing configuration; running services do not watch
or reload the file.
