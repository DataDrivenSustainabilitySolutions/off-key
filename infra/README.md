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
Never commit inventories, vaults, passwords, credentials, tailnet identity or backups.
The original private infrastructure repository remains the historical archive until
an operator verifies the first integrated release and archives it.
