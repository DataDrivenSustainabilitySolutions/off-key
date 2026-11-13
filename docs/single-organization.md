# Single-organization operation

One off/key installation serves one organization. Active members share the same
MQTT sources, telemetry, monitors, and anomalies. Favorites belong to the signed-in
member. Use separate installations and separate credentials for separate
organizations; this release does not provide tenant isolation inside one database.

Every active member can read the shared workspace and maintain their own
favorites. A role decides what a member can change. It bundles permissions:
**Manage sources** (catalogue, brokers, recording and live views), **Manage
monitors** (pipelines and monitors), **Manage alarms** (recording and deleting
alarms), **Use the Dojo** (offline datasets and runs) and **Manage members**
(members and roles). Two roles are built in:
Administrator always holds every permission, including ones a later release
adds, and cannot be changed; Member holds none until it is edited. **Account →
Roles** creates, edits and deletes further roles; a role cannot be deleted while
a member holds it. Members holding a role get a change on their next request.
Whoever can manage members can give any role, including their own, so grant it
deliberately. **Account → Signed in** shows your email, role and what it lets
you change. **Account → Members** supports email invitations with a role,
resending pending invitations, role changes, and disabling or enabling accounts.
Disabling preserves the account and its data and revokes access immediately.
Once disabled, a member can be permanently removed after confirmation. Removal
deletes the account, personal favorites and remembered sessions; shared catalogue
data, telemetry, monitors, reports and audit attribution remain. A removed member
needs a new invitation to return. Previous sessions and account links stay invalid
after reinvitation. The server rejects removal of active accounts and prevents
any change that would leave no active, verified member who can manage members. Concurrent access changes and
removal are serialized within the same membership transaction lock.

### Agents

An agent is a program that works through the API in place of a person, for
example an assistant that designs monitors. It signs in with a key instead of
an email and a password. **Account → Agents**, for members who can manage
members, creates a key under a name, shows it once and revokes it. Only a digest
of the key is stored, so a lost key is replaced, not recovered.

A key holds no role. Every key can read what a member reads about devices,
readings, designs, monitors, evidence and alarms, check and edit a design that
is not saved, and test a design on recorded history in the Dojo. **May start
monitors** additionally lets one key start a monitoring service. Without it the
agent hands its design to a member, who starts it. No key can stop, rename,
replace or delete a monitor, change the library, sources, labels, members,
roles or keys, and an operation added later is closed to keys until it is
opened on purpose. Revoking a key stops it with the next request. Monitors the
agent started keep running, and creating a key, changing what it may do,
revoking it and each service a key starts are logged as security events.

## Installation and upgrade

1. Configure a dedicated random `INTERNAL_API_SECRET` (at least 32 characters)
   in the API and TACTIC environments. Generate it with `openssl rand -hex 32`.
   Keep it separate from JWT, database, and MQTT credentials.
2. Set `FRONTEND_BASE_URL` to the externally reachable dashboard URL and configure
   SMTP. The development default is Mailpit, which captures mail rather than
   delivering it. Real organization invitations and password recovery require
   a working SMTP relay. Use authenticated TLS and certificate validation.
3. For an existing database, take a backup and pause the API, TACTIC, and db-sync
   during the upgrade. Apply migrations only through the packaged migration
   workflow described in
   [Collection](operations/system-collection.md#upgrade-from-the-previous-runtime);
   fresh databases are initialized by db-sync automatically. The membership
   migration preserves verified accounts, password hashes, roles, favorites, and
   telemetry; obsolete verification links are invalidated, and every existing login
   session must sign in again.
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
   runs this step automatically after readiness checks; `make -C infra invite-admin-prod`
   explicitly resends the initial invitation with private local recovery configuration.

   Without `--send-email`, the command retains its trusted-console behavior: print
   a one-time URL instead of emailing it. Treat that URL as a secret and deliver
   it directly to the configured mailbox owner; do not put it in logs or tickets.
   This mode refuses to issue an invitation once an active administrator exists.

For Resend, configure `SMTP_SERVER=smtp.resend.com`, `SMTP_PORT=587`,
`EMAIL_USERNAME=resend`, and `EMAIL_PASSWORD` as the real Resend API key.
Use `MAIL_STARTTLS=True`, `MAIL_SSL_TLS=False`, `USE_CREDENTIALS=True`, and
`VALIDATE_CERTS=True`. Set `EMAIL_FROM` to an address on your verified domain.
Both API and TACTIC need the mail settings; the frontend never needs the key.
See [Production releases](operations/production.md#credentials-ingress-and-certificates)
for the vault and deployment steps. Local Mailpit settings remain unchanged.

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

Rate limits are keyed by the client address. The gateway reads it from
`X-Forwarded-For` only when the connecting peer is in `TRUSTED_PROXY_CIDRS`
(loopback and private ranges by default), taking the nearest untrusted hop, so a
client cannot choose its own bucket. Traefik trusts the same private ranges so the
address cloudflared forwards survives. Sign-in and password-reset requests are
limited per client and account, so nobody can lock another person out, plus a
shared per-client budget across all credential endpoints; invitation and reset
tokens are limited per token. Run one API replica with the existing deployment;
adding replicas requires shared rate-limit storage or ingress limits.

Emails are matched case-insensitively and stored lowercase. "Remember me" keeps
the access token in page memory only; each tab restores it from the HttpOnly
cookie. The first refresh after a secret is a day old replaces it, and presenting
a replaced secret after a short grace period ends that sign-in everywhere.

## Validation

Run the backend test suite and frontend tests/build/lint. Set
`TEST_SCHEMA_DATABASE_URL` only to a disposable TimescaleDB database to also run
membership, migration, schema, and concurrency tests. For Playwright on a fresh
stack, set `E2E_BOOTSTRAP_URL` to the URL generated by the operator command; the
smoke-test workflow does this automatically and masks the URL.
