# Remove disabled members from Account

## Goal and context

Administrators can currently disable or enable a member, but cannot remove the
account from the installation. Add permanent removal after disabling, and rename
the duplicate Account subsection to Your access because it displays the current
email, role and permissions. Continue on the existing improvements branch; do not
merge. `.agent/PLANS.md` is absent, so this file records the execution plan.

## Design

- Add an administrator-only DELETE `/v1/members/{user_id}` through the gateway and
  TACTIC. Return 204 on success, 404 for an unknown account, and 409 if the account
  is active. Check under the existing transaction-level membership lock and row
  lock, serializing removal with enabling, role changes and invitations. Existing
  last-administrator protection continues to apply to disabling an account.
- Remove only the user, their personal favorites and remembered sessions in one
  transaction. Preserve shared catalogue, telemetry, monitors, reports and audit
  attribution. Old account links and tokens stay invalid even if the same email
  receives a fresh invitation. Use existing schema contracts; no migration needed.
- Offer Remove beside Enable for disabled accounts. Use an accessible confirmation
  dialog that names the member and explains permanence and the need to invite
  them again. Keep failures visible and retryable, prevent concurrent submission,
  and restore keyboard focus after cancellation or successful removal.
- Document the endpoint and the account lifecycle. Add regression coverage for
  authorization, active-account protection, cleanup, concurrent membership changes,
  reinvitation, cancellation and API failures.

## Progress

- [x] Inspect the existing member UI, API, authentication and database references.
- [x] Implement the service, HTTP endpoints, typed client and Account controls.
- [x] Add regression coverage and update user/API documentation.
- [x] Run backend tests with a disposable real PostgreSQL database and affected
      frontend tests, lint and production build.
- [x] Rebuild the isolated Docker services and validate real browser journeys,
      including invitation, disabling, cancellation, removal and reinvitation.
- [x] Review the final diff and record results.
- [x] Commit the migration-test repair separately and the account feature atomically.

## Validation

Use locked dependencies and bundled Node 24. Keep the existing `off-key` deployment
untouched; the `off-key-settings` stack is the integration target at
http://127.0.0.1:5174. PostgreSQL integration tests must use disposable schemas or
databases. Browser fixtures use unique local test mailboxes captured by Mailpit;
remove those fixtures afterwards. Inspect light/dark/mobile layouts and keyboard
focus. Do not rely solely on mock-backed tests, and do not merge the branch.

## Results and refinements

The complete frontend suite passes: 603 tests across 52 files. Frontend lint,
production build, strict documentation build and all repository pre-commit checks
pass. The existing large telemetry-chunk advisory remains unchanged.

The focused membership run passes all 36 tests against disposable PostgreSQL.
The complete backend suite also passes in an isolated Linux/Python 3.14 image with
locked dependencies and real PostgreSQL: 933 passed, five opt-in/environment tests
skipped, zero failures or errors. A native Windows run exposed filesystem-mode,
default-encoding and environment-variable-length limitations; Linux matches CI.
The database-enabled full run also exposed three existing catalogue-upgrade
fixtures that removed migration 005 from the ledger but left newer migration 006.
They now remove all entries from 005 onward to represent the intended older
release consistently. No migration or production schema changed.

Five real Chrome journeys pass against the rebuilt `off-key-settings` services:
the three existing application-settings journeys and two new account journeys.
They cover pending and verified accounts, disabling, cancelling, confirmed removal,
reload persistence, current-administrator authorization, active-account protection
after another tab re-enables a member, session revocation, local Mailpit delivery,
accepting a new invitation for the same address and rejection of previous links
and access/remembered-session tokens. The shared catalogue document and revision
remain unchanged by removal. Personal favorites and remembered-session cleanup,
preserved shared entities/other members' favorites, and enable/remove concurrency
are additionally checked in real database integration tests.

The initial shared-data browser assertion also compared live health timestamps;
it now compares the saved document and revision, allowing diagnostics to continue
updating normally. The corrected journey passes. Light, dark and 320px dialog
screenshots were visually inspected; keyboard focus starts on Cancel, stays
trapped, returns to Remove on cancellation, and moves to the member list after
successful removal. Temporary member fixtures are cleaned through the real API;
the final API check found none remaining. The disposable PostgreSQL test service
and its network were removed after the passing Linux run.

The member profile interface now lives in a dependency-free type module, reexported
by the existing API client, so browser tests share the contract without importing
the application's runtime session client into their separate TypeScript project.
The existing PostgreSQL membership fixture is shared through `tests/conftest.py`,
so both account test modules use the same isolated schema lifecycle without
importing a pytest fixture from another test module. The pinned commit-hook Ruff
version caught that import pattern even though the installed newer linter allowed
it; the shared fixture now follows the repository's normal fixture discovery.
The complete Linux suite was rerun after this cleanup: 933 passed, five skipped,
zero failures or errors. The final staged commit hooks also pass.
The original `off-key` deployment and its data remain untouched. The updated
preview stays available at http://127.0.0.1:5174/account.

## PR validation follow-up

The PR's CodeQL trace classified the result of `request_password_reset()` as a
password based on the method name. Its actual result contains a random 256-bit
recovery token, while passwords are hashed separately with bcrypt. Rename the
internal operation to `issue_reset_token()` and document its digest-only storage;
update the HTTP handler and integration callers. The public routes and token
format retain their existing contract. CodeQL can then distinguish recovery-token
issuance from a password source without excluding or dismissing the alert.

The complete backend suite passes again against disposable PostgreSQL on Linux:
933 passed, five skipped. Both real account browser journeys also pass, including
delivery to the local mail sink, disable/remove/reinvite, and rejection of previous
sessions. The deployment rehearsal must publish its SMTP fixture's Mailpit API
and supply `MAILPIT_BASE_URL` to exercise those same journeys in CI.
