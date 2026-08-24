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

| Workflow | Trigger | What it validates |
| --- | --- | --- |
| `ci.yml` | Pull requests, `main`, merge queue | Backend tests, pre-commit, frontend lint/test/build |
| `docker-validate.yml` | Pull requests, merge queue | Builds the service image matrix through the reusable workflow |
| `deployment-smoke.yml` | Relevant pull requests, `main`, manual | Compose rendering and full-system smoke paths |
| `docker-publish.yml` | `main` and version tags | Publishes and attests service images in GHCR |
| `auto-assignee.yml` | New or ready pull requests | Assigns reviewers according to repository configuration |
| `auto_request_review.yml` | New, reopened, or ready pull requests | Requests reviewers from the local review rules |

The reusable `docker-images.yml` defines the image matrix used for validation and publishing.

## Local quality gate

```bash
uv sync --project backend --all-packages --all-groups --frozen
uv run --project backend ruff check .
uv run --project backend python -m pytest -q
uv run --project backend pre-commit run --all-files
npm --prefix frontend ci
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

Run the smallest relevant tests while developing, then run the complete gate before requesting review.

## Commit hygiene

- Keep generated artifacts out of commits unless the project explicitly requires them.
- Preserve lockfile changes when dependency resolution intentionally changed.
- Treat `.env`, `.env.ingress.local`, credentials, and production endpoint details as local or secret-store data.
- Review `git diff --check` and the staged diff before pushing.

## Related pages

- [Developer setup](setup.md)
- [Environment variables](../reference/environment-variables.md)
- [Testing and debugging](testing-debugging.md)
