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
fails when a workflow file is missing here or the release gate is not marked.

Every check that gates a merge or a release is a job in `ci.yml`. Its `ci-gate` job
needs all other jobs and succeeds only when each of them succeeded, so it is the one
check the branch rule requires. Job names may carry matrix values such as a Python
or EMQX version; a version bump renames such a job without touching the rule, and
`infra/tests/test_ci_workflow.py` fails if a new job is left out of `ci-gate`.

| Workflow file | Name | Triggers | Checks | Release gate |
| --- | --- | --- | --- | --- |
| `ci.yml` | CI | Pull requests, `main`, merge queue, manual | `ci-gate` (required) needs every job: `backend (3.12)`, `backend (3.14)` (pre-commit, backend tests, generated contracts; the 3.12 leg also runs the `ty` type check); `frontend` (lint, tests, build, route-mocked journeys); `infrastructure` (Ansible syntax, rendered stack and `infra/tests`); `collection (5.8.7)`, `collection (6.3.2)` (`postgres` lane and real EMQX brokers); `radar` (`radar_integration` lane on Swarm with the production image); `images` on pull requests (builds the image matrix) or `publish` on `main` (pushes and attests the images); `deployment-smoke (rehearsal)` (browser journeys, then backup restore and binary rollback on a production Swarm) and `deployment-smoke (pipelines)` (adaptive monitor and visual pipelines on a second Swarm). On `main` both smoke lanes start after `publish` and test the images it pushed | yes |
| `docker-images.yml` | Docker Images | Called by CI | Reusable image matrix | no |
| `docs.yml` | Documentation | Pull requests and `main` that touch `docs/**`, `zensical.toml` or `requirements-docs.txt`, manual | `Build documentation` (strict build); `main` also deploys GitHub Pages | no |
| `deploy-production.yml` | Deploy Production | Completion of CI on `main`, manual | Deploys the newest main commit whose CI push run succeeded ([Production releases](../operations/production.md)), then the public demo stack while `DEMO_ENABLED` is on ([Public demo](../operations/public-demo.md)) | no |
| `ghcr-retention.yml` | GHCR Retention | Weekly, manual | Lists application image versions beyond the newest 20 releases per image, keeping `latest`, the committed release pins and the kept images' attestations; deletes them on a manual run with `delete` or weekly once the variable `GHCR_RETENTION_ENABLED` is `true` ([Image retention](../operations/production.md#image-retention)) | no |
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
