# Aberration (off-key)

Anomaly detection for connected systems: members describe MQTT or HTTP sources,
the stack collects their telemetry, runs streaming detection pipelines on it and
shows the evidence. FastAPI backend, React frontend, Docker Swarm in production.

These are defaults, not laws. If one fights the task in front of you, say so and
ask before breaking it. The published docs in `docs/` explain the system in depth;
read the page for the area you touch instead of guessing.

## Words we use

- **source**: a broker entry (MQTT broker or HTTP API) with entities, topics and payload fields.
- **reading**: one numeric field of a source over time.
- **pipeline / monitor**: a visual detection design (built in the composer) and its running activation.
- **step**: one node of a pipeline: a detector, transform, forecaster or rule.
- **RADAR**: the per-monitor detection workload. **TACTIC**: the background worker that starts and stops it.
- **Dojo**: offline replay of a pipeline against recorded data.
- **evidence**: what a monitor stores to explain an anomaly.

## Where code lives

- `backend/services/api/gateway`: the one HTTP API under `/v1`.
- `backend/services/middleware/tactic`: background worker (recording, activations, RADAR reconciliation).
- `backend/services/mqtt/{proxy,radar}`, `backend/services/db/sync`, `backend/services/forecast/service`.
- `backend/libs/core/src/off_key_core`: shared models and logic. Pipeline and Dojo schemas are canonical here.
- `frontend/src`: layered as `app → pages → features/* → domain → shared`.
  `frontend/eslint-layers.js` is the source of truth and lint enforces it; extend
  the table there rather than working around a layer error.
- `infra/`: Ansible and the production stack. `dev/local`: the local stack and fixtures.
- `docs/`: the published site (Zensical). `infra/tests/test_docs.py` checks parts of it.

## Generated files: never edit by hand

`frontend/src/types/*.generated.ts`, `frontend/src/Tests/support/fixtures/*.generated.json`
and `docs/reference/design-file.schema.json` come from the Pydantic models. Change
the model, then run
`uv run --project backend python backend/scripts/generate_pipeline_types.py`.
The check fails while they are stale.

## Before you push

Run `make check`. It picks the fast suites from what the branch changed (ruff,
`ty`, generated-contract checks, pytest, ESLint, knip, Vitest, build) and runs them
in CI's order. Add `ARGS=--browser` for frontend journeys (needs Docker).

- Every push spends GitHub Actions minutes. Push once per finished step, not
  work in progress, and only after `make check` passes.
- Do not run the heavy suites locally or re-run CI because `main` moved on. They
  run on `main` after merging; the `full-ci` label opts a PR in when a deployment
  or broker change needs them before merge.
- A green PR can merge without being updated to the newest `main`.

## Tests

- A bug fix starts with a test that fails on `main`, at the lowest level that
  shows it. Purely visual fixes get before/after screenshots instead.
- An environment-gated test must belong to a CI lane that runs it
  (`backend/tests/test_suite_layout.py` enforces this). Choose the marker, don't skip.
- No sleeps or retries to make a test pass. Fix flaky tests, don't rerun them.

## Running the app

- `docker compose up -d --build` for the plain stack at http://localhost:5173.
- `make local-init` then `make local-up` for the isolated local stack with
  fixture brokers; see `docs/development/local-deployment.md`.
- For UI changes, look at the result in a browser, light and dark, desktop and
  phone width, and attach screenshots to the PR.

## Do not

- Run `make deploy-prod`, `make deploy-demo` or anything under `infra/` that
  touches a real host unless asked. `RESET_DATABASE` erases a stack's database.
- Commit `.env` files, credentials, plans, research notes or agent scratch files.
  Notes and unmerged patches for larger architectural changes stay outside the repo.
- Add a comment to explain a workaround. Fix the cause or encode the rule in a
  type, test or lint rule. Docstrings that state intent on public interfaces are fine.

## Taste

- No backward compatibility for now: clean breaks are fine, and so is dropping
  data. Don't keep shims or old code paths.
- Don't keep complexity because it exists, and don't add machinery because it
  looks architectural.
- When you correct the same mistake twice, turn it into a check (type, lint rule,
  test or import boundary) instead of adding a line here.
- Write user-facing text in plain words: what happened and what to do next.
