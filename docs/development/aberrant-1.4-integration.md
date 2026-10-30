# ABERRANT 1.4 configuration integration

The cross-repository ExecPlan is maintained in ABERRANT at
`execplans/aberrant-1.4-off-key.md` (PRs #103 and #104). This coordinated change
keeps off-key's Python requirements, supported models, presets, resource limits,
feature binding, calibration and deployment policy. The generated offline catalog
continues to isolate the control plane from numerical imports.

RADAR resolves once during startup or preflight and reuses canonical configuration,
capabilities, fingerprint and construction. Checkpoints retain canonical
configuration and learned state; resolved constructor metadata is process-local.
The new runtime signature requires relearning and recalibration. Saved 1.3.0
launches are explicitly reviewed for normalization; historical records and
predecessor-run links remain unchanged.

Model discovery and the graph catalog serve the same bounded field descriptors.
Shared scalar, collection and nested controls distinguish omission, explicit null,
defaults and exclusive numeric bounds. Validation locations come from schemas,
Pydantic or ABERRANT, never from parsing messages.

Rollout order is backend metadata first, then the browser bundle. Rehearsal must
exercise old-browser/new-backend overlap, nested KNN, adjacency, null/default,
multiple errors and correction/publication, static/adaptive monitoring and mobile.
Binary rollback uses previous platform code and browser controls with the reviewed
1.4.0 numerical runtime at `9c010bda9831648f1db8c395dc0633f1302df757`.
The strict catalog, migration-ledger and numerical-version checks remain in place.
The separate 1.3.0 upgrade check preserves saved launches and starts fresh
learning when a checkpoint's runtime signature differs. Do not rewrite history or
weaken checkpoint compatibility to make upgrades or rollbacks appear resumable.

Candidate validation uses the built 1.4.0 wheel before publication. The final pin,
frozen lock and catalog must come from the published release. Required backend
3.12/3.14, frontend, generated-contract, real RADAR, deployment and rollback lanes
must run without skipped required integration tests.

Progress: ABERRANT 1.4.0 is published. The candidate wheel passed 206 real RADAR
integration tests with zero skips before publication. The final published pin,
frozen lock and generated catalog are installed. Backend unit/contract checks
passed on Linux 3.12 and 3.14 (1,347 tests each); structured diagnostics and saved
1.3.0 normalization passed against the published wheel. Browser, production
rehearsal and rollback verification are in progress. No production deployment has
been changed.
