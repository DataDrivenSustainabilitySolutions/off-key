# Deployment modes

This page documents the supported local, profile-based, and Swarm deployment patterns.

## When to use this page

Use this page when selecting or switching a run mode.

## 1. Local development — default

```bash
cp .env.example .env
docker compose up -d --build
```

Characteristics:

- One internal Mosquitto broker, `mosquitto`.
- A local `source-broker` for deterministic development.
- `mqtt-radar` is build-only; TACTIC launches its workloads.

Before creating a TACTIC-managed monitoring service for the first time, build its local image:

```bash
docker compose build mqtt-radar
```

## 2. Production Swarm

Production uses the single authoritative model under `infra/`, released through
GitHub Actions after all main checks pass. See [GitHub setup](github-setup.md),
[Production releases](production.md), and [Recovery](recovery.md).

```bash
make check-infra                                  # validate Ansible and the rendered stack
make deploy-prod REVISION=<full-tested-main-SHA>  # dispatch Deploy Production
```

## Safe mode switching

Stop the current mode before starting another:

```bash
docker compose down
```

If containers keep resolving stale names or networks after switching between the
local and ingress modes, remove the shared networks too:

```bash
docker network rm off-key_app-network off-key_mqtt-network || true
```

!!! warning
    `docker compose down -v` deletes local database and broker volumes. Use it only when a clean, destructive reset is intended.

## Mode selection guidance

| Goal | Recommended mode |
| --- | --- |
| Day-to-day development | Local default |
| Production and external broker ingress | Integrated production Swarm |

## Configuration reference

Use [Environment variables](../reference/environment-variables.md) for per-mode setup.

## Related pages

- [Getting started](../getting-started.md)
- [Architecture](../development/architecture.md)
- [Testing and debugging](../development/testing-debugging.md)
