# Single-organization operation

One off/key installation serves one organization. Active members share the same
MQTT sources, telemetry, monitors, and anomalies. Favorites belong to the signed-in
member. Use separate installations and separate credentials for separate
organizations; this release does not provide tenant isolation inside one database.

Administrators manage sources, monitors, anomalies, and members. Members can read
the shared workspace and maintain their own favorites. Account → Organization
members supports email invitations, resending pending invitations, role changes,
and disabling or enabling accounts. Disabling preserves the account and its data.
The server prevents removing the last active, verified administrator.

## Installation and upgrade

1. Configure a dedicated random `INTERNAL_API_SECRET` (at least 32 characters)
   in the API and TACTIC environments. Generate it with `openssl rand -hex 32`.
   Keep it separate from JWT, database, and MQTT credentials.
2. Set `FRONTEND_BASE_URL` to the externally reachable dashboard URL and configure
   SMTP. The development default is Mailpit, which captures mail rather than
   delivering it. Real organization invitations and password recovery require
   a working SMTP relay. Use authenticated TLS and certificate validation.
3. For an existing database, take a backup and pause the API, TACTIC, and db-sync
   during the upgrade. Apply the migration before starting the new services:

   ```sh
   docker compose exec -T timescaledb sh -c 'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < backend/migrations/001_membership.sql
   ```

   On Swarm, run the same SQL with `psql` against the installation database using
   operator credentials. Fresh databases are initialized by db-sync automatically.
   The migration is transactional and repeatable. It preserves verified accounts,
   password hashes, roles, favorites, and telemetry; obsolete verification links
   are invalidated. All existing login sessions must sign in again.
4. Start matching versions of all application services, then check readiness.
   Do not mix old and new API/TACTIC versions. The old schema checker rejects the
   added columns, so rolling back requires a coordinated database restore or a
   separately reviewed reverse migration.
5. Initialize the first administrator by email:

   ```sh
   docker compose exec -T tactic-middleware /app/bin/python -m off_key_tactic_middleware.bootstrap_admin --send-email
   ```

   The command emails `SUPERUSER_MAIL` and prints status JSON without the token.
   Open the invitation to choose a password; there is no default admin password.
   It preserves valid pending invitations and existing active administrators.
   Add `--resend` to replace a pending link, including after SMTP delivery failed.
   Other existing-account states require operator recovery and are not modified.
   On Swarm, execute the module inside a TACTIC task. Production infrastructure
   runs this step automatically after readiness checks; `make invite-admin-prod`
   in `off-key-infra` explicitly resends the initial invitation.

   Without `--send-email`, the command retains its trusted-console behavior: print
   a one-time URL instead of emailing it. Treat that URL as a secret and deliver
   it directly to the configured mailbox owner; do not put it in logs or tickets.
   This mode refuses to issue an invitation once an active administrator exists.

For Resend, configure `SMTP_SERVER=smtp.resend.com`, `SMTP_PORT=587`,
`EMAIL_USERNAME=resend`, and `EMAIL_PASSWORD` as the real Resend API key.
Use `MAIL_STARTTLS=True`, `MAIL_SSL_TLS=False`, `USE_CREDENTIALS=True`, and
`VALIDATE_CERTS=True`. Set `EMAIL_FROM` to an address on your verified domain.
Both API and TACTIC need the mail settings; the frontend never needs the key.
See the infrastructure repository's `docs/email-delivery.md` for domain, vault,
and deployment instructions. Local Mailpit settings remain unchanged.

Pending legacy registrations need a new invitation. Public registration and old
email-verification links no longer activate accounts. Invitation links expire in
48 hours; reset links expire in 30 minutes. Resending replaces the previous link.
Only hashes are stored. Successful use clears the token. Changing access or
resetting a password revokes existing sessions; reenabling does not restore them.
New passwords require at least 12 characters and at most 72 UTF-8 bytes.

## Operating boundary

The gateway checks current membership on every protected request. TACTIC business
routes require the API service credential; health and readiness remain public.
The internal TACTIC port is bound to localhost in development and is not published
by the Swarm stack. Keep databases, the Docker socket proxy, SMTP, and brokers on
private networks. Remote users enter through the HTTPS dashboard/API ingress.

The infrastructure renders a host-only `.env` and scoped `.env.<service>` files
with mode 0600. The frontend receives no backend credentials. MQTT secrets continue
to use targeted Swarm secret mounts. Deployment operators and Docker managers are
trusted: scoping credentials is not isolation against a compromised database or
orchestrator. Per-service database roles, external secret rotation, SSO, and
multiple organizations are separate work.

Authentication endpoints have per-process limits keyed by the target account or
single-use token. Users behind a proxy do not share one quota, and arbitrary
forwarded headers do not change the limit. Run one API replica with the existing
deployment; adding replicas requires shared rate-limit storage or ingress limits.

## Validation

Run the backend test suite and frontend tests/build/lint. Set
`TEST_SCHEMA_DATABASE_URL` only to a disposable TimescaleDB database to also run
membership, migration, schema, and concurrency tests. For Playwright on a fresh
stack, set `E2E_BOOTSTRAP_URL` to the URL generated by the operator command; the
smoke-test workflow does this automatically and masks the URL.
