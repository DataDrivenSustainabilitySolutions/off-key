# Contributing and CI

This page describes contribution expectations and automated pull-request checks.

## When to use this page

Use this page before opening a pull request and when matching local checks to CI.

## Branch and pull-request basics

- Open pull requests against `main` unless the repository workflow says otherwise.
- Keep changes scoped and explain the user-visible or operational impact.
- Update tests and documentation when behaviour, configuration, or interfaces change.
- Do not commit credentials, tokens, private keys, or local runtime environment files.

## Current automated checks

This table is the single inventory of GitHub workflows. `infra/tests/test_docs.py`
fails when a workflow file is missing here or a release gate is not marked.

| Workflow file | Name | Triggers | Checks | Release gate |
| --- | --- | --- | --- | --- |
| `ci.yml` | CI | Pull requests, `main`, merge queue | `pre-commit (3.12)`, `pre-commit (3.14)` (pre-commit, backend tests, generated contracts; the 3.12 leg also runs the `ty` type check), `frontend` (lint, tests, build) | yes |
| `collection-integration.yml` | MQTT Collection Integration | Pull requests, `main`, merge queue | `collection (5.8.7)`, `collection (6.3.2)`: `postgres` lane and real EMQX brokers | yes |
| `radar-production-integration.yml` | RADAR production integration | Pull requests, `main`, merge queue, manual | `RADAR production integration`: `radar_integration` lane on Swarm with the production image | yes |
| `deployment-smoke.yml` | Deployment Smoke | Pull requests, `main`, merge queue, manual | `deployment-smoke`: rehearses the production Swarm, browser journeys, backup restore and binary rollback | yes |
| `infra-validation.yml` | Infrastructure Validation | Pull requests, `main`, merge queue | `infrastructure`: Ansible syntax, rendered stack and `infra/tests` | yes |
| `docker-publish.yml` | Docker Publish | `main` and `v*` tags | `publish`: pushes and attests service images in GHCR | yes |
| `docker-validate.yml` | Docker Validate | Pull requests, merge queue | `docker-validate / docker-validate`: builds the image matrix | no |
| `docker-images.yml` | Docker Images | Called by Docker Validate and Docker Publish | Reusable image matrix | no |
| `docs.yml` | Documentation | Pull requests and `main` that touch `docs/**`, `zensical.toml` or `requirements-docs.txt`, manual | `Build documentation` (strict build); `main` also deploys GitHub Pages | no |
| `deploy-production.yml` | Deploy Production | Completion of every release gate on `main`, manual | Deploys the newest commit whose release gates all succeeded ([Production releases](../operations/production.md)) | no |
| `pr-triage.yml` | PR triage | Pull requests opened, reopened or marked ready | Assigns a human author and requests the maintainer's review; never fails | no |
| CodeQL default setup | CodeQL | Repository settings | `CodeQL` | no |

Shared steps live in `.github/actions/setup-backend` (Python, the pinned uv release
and the locked backend sync). Test lanes select their tests by pytest marker; see
[Testing and debugging](testing-debugging.md#radar-production-integration).

## Local quality gate

```bash
uv sync --project backend --all-packages --all-groups --frozen
uv run --project backend ruff check .
uv run --project backend ty check --project backend
uv run --project backend python -m pytest -q
uv run --project backend pre-commit run --all-files
npm --prefix frontend ci
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
python -m pip install -r requirements-docs.txt && zensical build --clean --strict
```

Preview the documentation with `zensical serve`.

Run the smallest relevant tests while developing, then run the complete gate before requesting review.

## Commit hygiene

- Keep generated artifacts out of commits unless the project explicitly requires them.
- Preserve lockfile changes when dependency resolution intentionally changed.
- Treat `.env`, encrypted production vaults, inventories and credentials, and production endpoint details as local or secret-store data.
- Review `git diff --check` and the staged diff before pushing.

## Related pages

- [Developer setup](setup.md)
- [Environment variables](../reference/environment-variables.md)
- [Testing and debugging](testing-debugging.md)
