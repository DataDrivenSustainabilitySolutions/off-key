# Environment variables

This page is the canonical runtime-configuration reference for the tracked environment templates.

## When to use this page

Use this page when configuring local, cluster, Swarm, or external-ingress deployments.

## Configuration files

| File | Purpose | Commit policy |
| --- | --- | --- |
| `.env.example` | Tracked local-development template | Commit-safe placeholders only |
| `.env` | Local Compose and application configuration | Never commit |
| `.env.ingress.example` | Tracked Swarm ingress template | Commit-safe placeholders only |
| `.env.ingress.local` | Ingress credentials, upstream, and host state path | Never commit |

Create the local files from the templates:

=== "Bash"

    ```bash
    cp .env.example .env
    cp .env.ingress.example .env.ingress.local
    ```

=== "PowerShell"

    ```powershell
    Copy-Item .env.example .env
    Copy-Item .env.ingress.example .env.ingress.local
    ```

!!! important
    Secret-bearing values are intentionally not reproduced in this documentation. Variable names and validation requirements are safe to document; runtime values belong in ignored files or a production secret store.

## Secret handling rules

Treat the values of these variables as secrets:

| Variable | Requirement |
| --- | --- |
| `JWT_SECRET` | Unique signing secret, at least 32 characters; do not reuse between environments |
| `JWT_VERIFICATION_SECRET` | Unique verification/reset signing secret, distinct from `JWT_SECRET` |
| `EMAIL_PASSWORD` | SMTP credential when authenticated delivery is enabled |
| `POSTGRES_PASSWORD` | Unique database credential outside disposable local development |
| `EMQX_DASHBOARD_PASSWORD` | Unique EMQX administrative credential |
| `EMQX_NODE_COOKIE` | Shared only by trusted nodes in the same EMQX cluster |
| `MQTT_APIKEY` | Required only when MQTT authentication is enabled |
| `INGRESS_TS_AUTHKEY` | Bootstrap credential for the Tailscale ingress node |

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
| `JWT_VERIFICATION_SECRET` | Not documented | Verification and reset-token signing secret |
| `ALGORITHM` | `HS256` | Must match the backend JWT implementation |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Positive access-token lifetime |
| `SUPERUSER_MAIL` | Local placeholder address | Email promoted to the administrator role during registration |

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
| `MQTT_BROKER_HOST` | `source-broker` | Source MQTT host |
| `MQTT_BROKER_PORT` | `1883` | Source MQTT port |
| `MQTT_USE_TLS` | `false` | TLS for the source client |
| `MQTT_USE_AUTH` | `false` | Source-broker authentication toggle |
| `MQTT_SOURCE_TOPICS` | `device/#` | MQTT subscription filter; current payload topics use `device/evCharger/<charger_id>/<telemetry_type>` |
| `MQTT_TELEMETRY_ENABLED` | `true` | Persist parsed source telemetry |

When `MQTT_USE_AUTH=true`, provide the supported `MQTT_USERNAME` and `MQTT_APIKEY` runtime variables through an ignored file or secret store.

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
| `RADAR_SUBSCRIPTION_TOPICS` | Three simulator sensor topics | Comma-separated concrete topics or valid filters |

## Internal services, retention, and logging

| Variable | Development default | Purpose / validation |
| --- | --- | --- |
| `SYNC_HOSTNAME` | `db-sync` | DB Sync service hostname |
| `SYNC_API_HOST` | `0.0.0.0` | DB Sync bind address |
| `SYNC_API_PORT` | `8009` | DB Sync internal API port |
| `TELEMETRY_RETENTION_DAYS` | `14` | Retention for telemetry and monitoring evidence; integer `1–365` |
| `LOG_LEVEL` | `INFO` | Standard log-level token |
| `LOG_FORMAT` | `simple` | Supported log output format |
| `LOG_REDACT_PII` | `true` | Keep enabled where logs may contain user data |
| `LOG_PII_DEBUG_UNMASK` | `false` | Never enable in shared or production environments |
| `ENABLE_REQUEST_LOGGING` | `true` | HTTP request logging toggle |
| `ENABLE_PERFORMANCE_LOGGING` | `true` | Performance logging toggle |

## Swarm image overrides

The tracked `.env.example` includes commented placeholders for immutable images:

- `API_GATEWAY_IMAGE`
- `FRONTEND_IMAGE`
- `MQTT_PROXY_IMAGE`
- `MQTT_RADAR_IMAGE`
- `TACTIC_MIDDLEWARE_IMAGE`
- `DB_SYNC_IMAGE`

Use an immutable release or commit tag. Do not deploy floating development tags when reproducibility matters.

## Ingress overlay

| Variable | Default / requirement | Purpose |
| --- | --- | --- |
| `INGRESS_TS_AUTH_ONCE` | `true` recommended | Reuse persisted Tailscale state and authenticate only when needed |
| `INGRESS_TS_AUTHKEY` | Secret; required for first login unless state is pre-seeded | Tailscale bootstrap credential |
| `INGRESS_TS_EXTRA_ARGS` | `--accept-dns=false` | Extra `tailscale up` flags |
| `INGRESS_TS_STATE_DIR` | Required host path | Persistent Tailscale state directory on the backend node |
| `INGRESS_UPSTREAM_MQTT_HOST` | Required | Upstream broker MagicDNS hostname |
| `INGRESS_UPSTREAM_MQTT_PORT` | `1883` | Upstream broker port |

See [Deployment modes](../operations/deployment-modes.md) for the render-and-deploy command and EMQX bridge requirements.

## Troubleshooting by variable group

| Symptom | Likely variables | First action |
| --- | --- | --- |
| Frontend loads but API calls fail | `VITE_API_URL`, `BACKEND_PORT`, `CORS_ALLOWED_ORIGINS` | Align the URL with host/container reachability and CORS |
| Verification/reset links are wrong | `FRONTEND_BASE_URL` | Set the externally reachable frontend URL |
| SMTP delivery fails | `SMTP_*`, `EMAIL_*`, TLS and credential toggles | Match the provider transport and authentication requirements |
| No source telemetry | `MQTT_BROKER_*`, `MQTT_SOURCE_TOPICS`, MQTT auth/TLS | Verify reachability, topic shape, and credentials |
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
