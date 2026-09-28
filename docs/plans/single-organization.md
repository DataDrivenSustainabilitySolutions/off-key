# Single-organization membership and access

One installation serves one organization. Administrators manage members, sources,
and monitoring workloads. Members read shared operational data and manage their
own favorites. MQTT credentials and vendor network access remain operator settings.

## Implementation

1. Require current, verified, active membership for operational API routes.
   Check database state for each session and authenticate Gateway-to-TACTIC calls
   independently. Keep liveness and readiness available to deployment probes.
2. Close public registration. Provide operator bootstrap and administrator-issued
   invitations, role changes, and access revocation. Serialize membership changes
   to protect the last administrator. Hash and expire single-use invitation/reset
   tokens. Revoke existing sessions after disabling access or resetting a password.
3. Replace the account placeholder with account details and member management.
   Invitation recipients choose their password. Keep the API authoritative for
   all permissions, including monitoring and anomaly mutations.
4. Provide an explicit transactional schema migration that preserves existing
   users and telemetry. Scope runtime configuration to its consuming services.
   Document SMTP delivery and update CI's initial-account flow.

## Verification and rollout

Test missing/invalid authentication, member/admin permissions, forged favorite
ownership, revoked sessions, token replay/expiry, and last-administrator protection.
Run backend and frontend checks, infrastructure rendering checks, and full-stack
smoke tests when available. Review the candidate for concrete bypasses/regressions.

Before deployment, publish matching application images, back up the database,
and apply the membership migration. Existing accounts retain access until reviewed
and disabled by an administrator. Existing sessions must sign in again. Configure
a real SMTP relay for invitations and resets; Mailpit is for development/pilots.
Deployment is a separate operator action.
