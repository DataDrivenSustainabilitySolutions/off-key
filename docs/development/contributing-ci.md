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
needs all other jobs, so it is the one check the branch rule requires. It succeeds
only when the `changes` job wrote a plan, every job the plan selected succeeded and
every job it did not select was skipped; a failed, cancelled or unplanned result
fails it. Job names may carry matrix values such as a Python or EMQX version; a
version bump renames such a job without touching the rule, and
`infra/tests/test_ci_workflow.py` fails if a new job is left out of `ci-gate` or the
plan.

| Workflow file | Name | Triggers | Checks | Release gate |
| --- | --- | --- | --- | --- |
| `ci.yml` | CI | Pull requests, `main`, merge queue, manual | `ci-gate` (required) needs every job: `changes` (plans the run); `lint` (pre-commit, the `ty` type check and generated contracts, once); `contracts` (tests that read documentation or frontend sources, only when the full suites are planned out); `backend (3.12)`, `backend (3.14)` (backend tests); `frontend` (lint, tests and build); `frontend browser` (route-mocked journeys against that checked build); `infrastructure` (Ansible syntax, rendered stack and `infra/tests`); `collection (5.8.7)`, `collection (6.3.2)` (`postgres` lane and real EMQX brokers); `radar` (`radar_integration` lane on Swarm with this run's RADAR image); `images` on pull requests, the merge queue and manual runs (builds every image once, checks the frontend's delayed API start and keeps a run-scoped archive) or `publish` on `main` (pushes and attests the images); `deployment-smoke (rehearsal)` (every deployment test on a production Swarm: the adaptive monitor, then backup restore and binary rollback over state the test creates) and `deployment-smoke (browser)` (every browser journey on a second Swarm, visual pipelines last). On `main` RADAR and both smoke lanes test the images `publish` pushed | yes |
| `docker-images.yml` | Docker Images | Called by CI on `main` | Publishes and attests the image matrix, including the strict Zensical docs build | no |
| `deploy-production.yml` | Deploy Production | Completion of CI on `main`, manual | Deploys the newest main commit whose CI push run succeeded and kept its `production-release` evidence ([Production releases](../operations/production.md)) | no |
| `ghcr-retention.yml` | GHCR Retention | Weekly, manual | Lists application image versions beyond the newest 20 releases per image, keeping `latest`, the committed release pins and the kept images' attestations; deletes them on a manual run with `delete` or weekly once the variable `GHCR_RETENTION_ENABLED` is `true` ([Image retention](../operations/production.md#image-retention)) | no |
| `pr-triage.yml` | PR triage | Pull requests opened, reopened or marked ready | Assigns a human author and requests the maintainer's review; never fails | no |
| CodeQL default setup | CodeQL | Repository settings | `CodeQL` | no |

Shared steps live in `.github/actions/setup-backend` (Python, the pinned uv release
and the locked backend sync). Test lanes select their tests by pytest marker; see
[Testing and debugging](testing-debugging.md#radar-production-integration).

### Planned runs

`.github/scripts/ci_plan.py` narrows only two kinds of change; every other path,
and anything it cannot classify, runs every job:

| Changed paths | Jobs that run |
| --- | --- |
| Only root-level `*.md` | `lint`, `contracts` |
| Those plus `frontend/**`, except `frontend/Dockerfile`, `.dockerignore`, `.npmrc`, `package.json` and `package-lock.json` | `lint`, `frontend`, `frontend browser`, `contracts`, `images` or `publish`, both `deployment-smoke` lanes |
| Published docs (`docs/**`, `dev/docs/**`, `zensical.toml`) and anything else: backend and shared core, lockfiles and dependency manifests (including `requirements-docs.txt`), Dockerfiles, `infra/**`, `.github/**`, unknown files | every job |

Pull requests compare their merge commit with its base parent, the merge queue
compares the group with its base, and manual runs always run every job. A `main`
push compares with the newest ancestor whose CI run kept the `production-release`
artifact, so a cancelled or superseded run never hides a change. Deletions and
renames count both paths. An empty or unreadable diff, an unexpected checkout or
an API failure selects every job. `infra/tests/test_ci_plan.py` covers these
cases and fails when a backend or infrastructure test outside the `contracts` job
starts reading documentation or frontend sources.

A root-Markdown-only `main` run succeeds without publishing or rehearsing images,
so it keeps no release evidence; [production release selection](../operations/production.md)
skips it. Cheap checks run first: backend, infrastructure, collection,
observability, image and RADAR jobs wait for `lint`, and the deployment rehearsals
also wait for `frontend`. The independently required `frontend browser` job verifies
and unpacks that run's checked build using its SHA-256 output, then runs mocked
journeys while the Swarms prepare. Mocked journeys run once with two isolated
workers; production journeys keep one worker for shared catalogue/member state.
The input-picker expiry test controls only browser time over real MQTT receipts;
the sidebar journey still exercises the full two-minute expiry in real time.

`make -C infra check-deploy` runs each infrastructure test in a worker process of
its own, one per processor (`infra/tests/run_suite.py`). A class with a shared
fixture stays whole, and the run fails unless every discovered test ran. From
`infra`, `python -m unittest discover -s tests` is the serial equivalent.

Each rehearsal lane ends by reporting where its deployments spent their time:
Ansible task names and durations only, as the production deployment log prints
them, and the duration of the readiness checks between them.

### Image builds

`infra/scripts/image_sources.py` selects each image's source revision from its
complete committed input paths. All backend paths are shared backend inputs;
frontend and documentation inputs are separate. Build-tool and workflow edits
invalidate every image. The selected revision's input tree must equal the tested
checkout's tree; shallow history disables reuse. Stable revision/version labels
let unchanged builds retain their digest instead of replacing it for each release.
Every selected build, test and attestation still runs. Rehearsed release evidence
records the source revision per image, and deployment recomputes these revisions
before checking the registry labels. Older release evidence retains its original
all-images-at-the-release-SHA validation.

On pull requests, the merge queue and manual runs, the `images` job builds each
application image once with the inputs the rehearsals test (the `production`
frontend target, the service build arguments, `GIT_COMMIT` and the
`org.opencontainers.image.revision` label, all from
`infra/tests/rehearsal_releases.py`). It exports them as one zstd archive, kept as
a one-day artifact of that run only, and passes the archive digest and every image
ID as job outputs. RADAR and both rehearsal lanes load the archive only after the
digest, image IDs and revision labels match those outputs, then push it to their
own disposable registry; CI never rebuilds a current image elsewhere. Pull
requests never receive registry write credentials and their archive is never
promoted. On `main`, `publish` pushes and attests the images with the same build
inputs, and RADAR and the rehearsals test those published digests, which the
release then deploys.

Image builds read the validation cache and the publishing cache on main. BuildKit
still checks the Dockerfile, build arguments and input files; a cache hit does not
skip any test. The compatible rollback release is still built from its separately
reviewed source revision, with an additional cache scoped to that revision and
service. Current-image cache writes remain owned by the `images` and `publish`
jobs, avoiding competing exports from lanes.

`.github/actions/run-with-build-cache` gives CLI builds the cache runtime
credentials GitHub supplies to JavaScript actions. They are inherited only by that
command and its children, not written to `GITHUB_ENV` for subsequent test steps.
Local rehearsals keep using ordinary Docker builds without GitHub credentials.

Backend images retain the complete installed runtime but put workspace packages
and third-party dependencies in separate layers. Source-only changes can reuse
the larger dependency layer on registry pushes and node pulls. This reduces update
traffic and repeated storage; the first installation remains approximately the
same size.

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
