# Aberrant adaptive-stream lane

This ExecPlan is a living implementation record. Keep Progress, Discoveries, Decision Log, and Outcomes current while the work proceeds.

## Purpose

Add a production adaptive monitoring lane backed by `aberrant==0.5.0`. A user can configure one of the 24 published numeric detectors, warm it on aligned telemetry, calibrate and freeze a score threshold, then see every operational anomaly score and threshold in the telemetry charts. The existing static conformal lane must remain behaviorally compatible.

## Progress

- [x] Inspect the current static-only contracts, RADAR lifecycle, evidence storage, and chart implementation.
- [x] Verify the published `aberrant` 0.5.0 wheel and choose its 24-detector API.
- [x] Add shared adaptive configuration, catalog metadata, registry entries, and orchestration transport.
- [x] Add the adaptive RADAR pipeline, lifecycle, checkpoint state, health reporting, and result semantics.
- [x] Generalize evidence persistence and migrate existing static rows safely.
- [x] Enable the dynamic setup lane and strategy-aware evidence charts.
- [x] Complete real detector, persistence, frontend, and opt-in end-to-end verification coverage.
- [x] Harden the integrated lane after review: strategy-scoped model resolution,
  canonical sensor schemas, idempotent online migration, strategy-aware health,
  lossless nullable parameters, and mandatory deployment E2E coverage.

## Discoveries

- The repository currently accepts only `static_baseline`; the dynamic lane is a disabled frontend card.
- PyPI 0.5.0 differs from unreleased `main`: it exposes 24 selected detectors and declares `faiss-cpu` as a base dependency.
- `aberrant` pipelines implement streaming `score_one` and `learn_one`; calibration and operation must call score before learn.
- The built-in `QuantileThreshold` is rolling and excludes quantile 1.0, so the frozen empirical threshold belongs in the off-key adapter.
- Existing monitoring evidence requires a non-null conformal p-value and charts martingale evidence on a logarithmic pane; both contracts must become strategy-aware.
- The repository references `.agent/PLANS.md`, but that file is absent. This document follows the requested root-level ExecPlan convention.

## Decision Log

- Strategy ID is `adaptive_stream`; default model is `aberrant_online_isolation_forest`.
- Dependency is exactly `aberrant==0.5.0`, resolved and hashed by `uv.lock`.
- Catalog includes the 24 public numeric detector classes in the wheel. Utility, deep, and unreleased models are excluded.
- Warm-up and calibration defaults match the static lane: 1,200 and 360 aligned points.
- Calibration uses `numpy.quantile(scores, q, method="higher")`, default `q=1.0`; alarms use strict `score > threshold`.
- Warm-up and calibration do not emit evidence. Every successfully learned operational point emits score and threshold evidence; every exceeding point emits an anomaly.
- Preprocessing permits zero or one scaler followed by zero or one projection.
- Runtime construction uses a code allowlist. Registry import paths never authorize arbitrary imports.
- A single shared resolver owns strategy defaults and compatibility validation at
  Gateway, TACTIC, and RADAR boundaries; callers cannot select a model from the
  other strategy family.
- Sensor feature schemas use the same canonical key derivation as RADAR and
  reject topic-to-key collisions before workload creation.
- The evidence constraint is added `NOT VALID` and validated once. Subsequent
  DB-sync starts inspect PostgreSQL catalogs and issue no migration DDL after the
  schema reaches its target state.

## Implementation approach

Define the adaptive schemas and immutable catalog in the shared core package. Seed both static and adaptive model families in TACTIC, validate model and preprocessing parameters there, and pass a normalized `RADAR_ADAPTIVE_STREAM_CONFIG` to the workload. Keep the existing static wire shape compatible while requiring the strategy-specific adaptive config for adaptive requests.

Implement an `AdaptiveStreamDetectionService` behind the detector interface used by RADAR. It owns the aberrant pipeline, lifecycle counters, calibration scores, frozen threshold, feature schema, health statistics, and checkpoint payload. KNN gets an internal `FaissSimilaritySearchEngine` built from flattened JSON parameters. Sensor key arguments are derived from the aligned schema. Runtime validation computes the effective feature count after projection and rejects incompatible models before service start.

Generalize monitoring evidence with a strategy discriminator, model type, and nullable anomaly score/p-value fields. Use the existing DB-sync service for an idempotent compatibility migration and retain the current primary key and cursor ordering. Dynamic anomaly rows use `value_type=anomaly_score`.

Add a dedicated adaptive setup component that shares topic ownership behavior with the static component. Generalize the chart model into telemetry, static evidence, and adaptive score panes. Dynamic score and threshold are separate linear series so both values participate in axis tooltips; static martingale series remain logarithmic.

## Validation

Run shared schema/catalog tests, all backend unit and integration tests, real parameterized smoke/lifecycle/checkpoint tests for all 24 aberrant detectors and four transforms, frontend unit/build/lint tests, PostgreSQL migration tests, and the monitoring browser flow. Exercise a real OnlineIsolationForest service across Gateway, TACTIC, Docker RADAR, MQTT, and PostgreSQL, plus a real KNN/FAISS container smoke test. Static monitoring tests are mandatory regressions.

## Outcomes

Implemented the complete adaptive lane across shared contracts, Gateway, TACTIC,
RADAR, DB-sync, evidence APIs, and the frontend. The locked environment contains
Aberrant 0.5.0 and FAISS. Real parameterized tests exercise all 24 detectors,
all four transforms, strict lifecycle ordering, frozen quantile calibration, and
KNN/FAISS checkpoint continuation.

Verification at completion:

- Backend and RADAR: 502 passed, 1 skipped in the local suite. The sole skip is
  the stack-dependent Gateway-to-PostgreSQL lifecycle test; deployment smoke CI
  explicitly enables and executes it against the live Compose stack.
- Frontend: 137 passed; ESLint and the production TypeScript/Vite build pass.
- Deployment smoke runs both the browser lifecycle and backend lifecycle tests.
  They create a real OnlineIsolationForest service through Gateway and TACTIC,
  publish through EMQX, and observe operational evidence persisted by RADAR.
- Browser publication uses the EMQX management API, so validation does not
  depend on an undeclared broker utility container.
