# Production infrastructure

This directory is the authoritative Ansible and Docker Swarm deployment for Offkey.
Application and infrastructure changes share a tested commit. Local development uses
root `docker-compose.yml`; VM provisioning and Windows/network setup are retired.

Start with [GitHub setup](../docs/operations/github-setup.md), then use the
[production runbook](../docs/operations/production.md) and
[recovery runbook](../docs/operations/recovery.md).

```sh
make -C infra setup
make check-infra
# After GitHub setup and a tested main commit:
make deploy-prod REVISION=<full-main-commit-sha>
```

The root deploy command dispatches GitHub Actions. Direct Ansible commands under
`infra/Makefile` remain available for controlled provisioning and recovery.

The public page at `aberration.app` is the self-contained
[`stack/landing.html.j2`](stack/landing.html.j2) template, served separately from
the dashboard. Its system font, light/dark colour tokens, and controls mirror
`frontend/src/App.css`; update both when the application palette changes.
The page follows the visitor's system colour scheme using CSS and needs no
scripts, external assets, or backend access. Dashboard links use the configured
`frontend_base_url`; legacy account/API forwarding remains in Traefik.
The monochrome mark and favicon come from [`../assets/brand/`](../assets/brand/);
run `python assets/brand/export.py` from the repository root after editing the
master SVG. The export preserves the page's surrounding design.

Never commit inventories, vaults, passwords, credentials, tailnet identity or backups.
The original private infrastructure repository remains the historical archive until
an operator verifies the first integrated release and archives it.
