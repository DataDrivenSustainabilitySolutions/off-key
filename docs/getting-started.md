# Getting started

This guide gets you from a fresh clone to a running local stack.

## When to use this page

Use this page for first-time local startup and health validation before deeper user or developer workflows.

## Audience

- New users who want to run the platform locally.
- New developers who need a known-good baseline before changing code.

## Prerequisites

- Docker Engine with the Docker Compose plugin.
- At least 8 GB RAM available to Docker.
- Available host ports: `5173`, `8000`, `8001`, `5432`, `1025`, `1883`, `1884`, `8025`, `8083`, `8084`, `8883`, and `18083`.

## 1. Configure the environment

Create the ignored local configuration file from the tracked development template:

```bash
cp .env.example .env
```

Before using Off-Key outside local development, replace every example credential. At minimum, configure:

- `EMQX_DASHBOARD_PASSWORD` with a strong value.
- `JWT_SECRET` and `JWT_VERIFICATION_SECRET` with distinct values of at least 32 characters.
- `SUPERUSER_MAIL` with the intended administrator mailbox.

Generate independent random values without writing them to documentation or source control:

=== "Bash"

    ```bash
    openssl rand -hex 32
    ```

=== "PowerShell"

    ```powershell
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    [Convert]::ToHexString($bytes).ToLower()
    ```

See [Environment variables](reference/environment-variables.md) for the configuration catalog and validation rules.

## 2. Start the stack

From the repository root:

```bash
docker compose up -d --build
```

The standalone RADAR and MQTT simulator services are profile-gated and do not start in the baseline stack.

## 3. Verify the stack

```bash
docker compose ps
```

The core services should be running; health-checked services should become `healthy` after their startup grace periods.

```bash
curl http://localhost:8000/health
curl http://localhost:8001/ready
```

| Interface | URL |
| --- | --- |
| Frontend | `http://localhost:5173` |
| Mailpit | `http://localhost:8025` |
| EMQX dashboard | `http://localhost:18083` |

## 4. Create the first user

1. Register in the frontend.
2. Open Mailpit and follow the verification link.
3. Verify the account.
4. Log in and open the charger overview.

## 5. Prepare monitoring when needed

TACTIC creates one RADAR workload per monitoring service. Build the local RADAR image before starting the first monitoring service, and rebuild it after RADAR source or dependency changes:

```bash
docker compose build mqtt-radar
```

## 6. Stop or reset

Stop containers while retaining volumes:

```bash
docker compose down
```

Delete local containers and volumes only when you intentionally want a full data reset:

```bash
docker compose down -v
```

!!! warning
    `docker compose down -v` deletes the local database and other named-volume data for this Compose project.

## Common first-run issues

| Symptom | Likely cause | First action |
| --- | --- | --- |
| API gateway keeps restarting | Database schema or TACTIC is not ready | Wait for startup, then inspect `db-sync`, `tactic-middleware`, and gateway logs |
| EMQX fails its health check | Dashboard password is missing or the persisted node state has incompatible bootstrap settings | Check `.env`; recreate the local EMQX volume only if its data can be discarded |
| Verification email is missing | Mailpit is unavailable | Check the `mailpit` service and open its UI |
| Frontend cannot reach the API | Vite proxy target or runtime API URL is wrong | Check `VITE_API_URL` for the selected run mode |
| Monitoring start cannot find its image | Local RADAR image has not been built | Run `docker compose build mqtt-radar` |

## Related pages

- [Web app](user-guide/web-app.md)
- [Developer setup](development/setup.md)
- [Deployment modes](operations/deployment-modes.md)
- [Testing and debugging](development/testing-debugging.md)
