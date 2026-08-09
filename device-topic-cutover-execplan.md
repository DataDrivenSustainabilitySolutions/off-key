# Device topic cutover

This ExecPlan is a living implementation record. Keep Progress, Discoveries,
Decision Log, and Outcomes current while the work proceeds.

## Purpose

Make `device/#` the only Off-Key telemetry namespace. Messages received as
`device/evCharger/<charger_id>/<telemetry_type>` must be validated, persisted,
returned by the existing APIs, available to RADAR, and rendered in the deployed
GUI. The established image publishing and Swarm deployment flow remains intact;
EMQX integration configuration uses an automatically managed named volume
without adding a node-placement or storage-management prerequisite.

## Progress

- [x] Inspect the current topic, ingestion, monitoring, GUI, and image-publish paths.
- [x] Replace backend and simulator topic and payload contracts.
- [x] Replace frontend topic construction, parsing, ownership, and validation.
- [x] Make EMQX ingress persistent and reproducibly reconcilable within the
  existing deployment workflow.
- [x] Update documentation and automated coverage.
- [x] Complete backend, frontend, and deployment-model validation; validate the
  live EMQX resource contract and proxy readiness.
- [ ] Re-run the five-message browser acceptance path in CI or deployment; the
  local Docker engine stopped before the final publish command.

## Discoveries

- The prior canonical namespace is embedded in shared Python validation, proxy and
  RADAR defaults, the simulator, frontend monitoring flows, tests, and runbooks.
- The GUI already discovers chargers and telemetry types from persisted rows; it
  does not and should not connect directly to MQTT.
- The combined EMQX rule counter aggregated independent `t/#` and bridge inputs.
  Device topics continue to arrive after removing `t/#`, so it is unrelated to
  Off-Key ingress.
- The repository references `.agent/PLANS.md`, but that file is absent. This
  document follows the existing root-level ExecPlan convention.

## Decision Log

- The only accepted filter is `device/#`; concrete telemetry uses the fixed
  prefix `device/evCharger/`.
- `charger_id` remains the public domain name. The fixed `evCharger` segment is
  not part of the ID.
- The telemetry type is the complete non-empty tail after the charger ID.
- Payload values must be finite numbers or numeric strings. A missing timestamp
  uses ingestion time; a supplied invalid timestamp rejects the message.
- No compatibility parser or persisted-monitoring migration is added.
- The bridge-only EMQX rule republishes the original topic and payload. `t/#`
  remains outside this pipeline.
- Image-variable names, GitHub Packages publishing, and the existing deployment
  invocation are intentionally unchanged; the topic cutover integrates into
  that flow instead of replacing it.
- The EMQX named volume provides automatic same-node persistence. Cross-node
  volume continuity remains an infrastructure concern outside this topic cutover;
  no new node label or storage-preparation contract is imposed.
- Reconciliation succeeds only after the live API reflects the canonical
  configuration and connector/Source status is `connected`; check-only mode
  applies the same verification without mutating EMQX.

## Implementation approach

Change the shared Python topic utilities first and make the proxy parsing boundary
reject unusable values. Carry the canonical format into proxy/RADAR Pydantic
defaults, TACTIC orchestration, and the simulator. Add one TypeScript topic module
and route all monitoring topic construction and ownership checks through it.

Persist EMQX data in an automatically managed Swarm volume and add a
secret-driven reconciliation utility for the named MQTT connector, Source,
bridge-only rule, and Republish action. The utility initializes the isolated CI
integration environment and remains optional for production diagnostics; the
existing deployment workflow gains no new step, label, or variable.

## Validation

Run focused topic/parser/config suites, then the affected backend and frontend
suites, lint/type/build checks, rendered Compose validation, and the live stack
path. The end-to-end fixture publishes the five representative upstream topics
and proves unchanged local delivery, persistence, API discovery, and GUI charts.

## Outcomes

The canonical topic contract is implemented across ingestion, simulation, RADAR,
TACTIC orchestration, the frontend, tests, examples, and ingress configuration.
The existing deployment and GitHub Packages mechanism is preserved. Local EMQX
6.2.2 accepted the reconciler twice (create, then update), reported the Source as
connected on `device/#`, and the rebuilt proxy reported
`source_subscriptions={"device/#": true}`. Backend tests, frontend tests, lint,
formatting, builds, and Compose renders pass. The final five-message browser run
remains delegated to the deployment smoke workflow because Docker Desktop stopped
before the local publish command completed.
