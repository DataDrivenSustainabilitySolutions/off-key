-- Run with psql -v ON_ERROR_STOP=1 before deploying the membership release.
-- Existing users retain access; audit that list after the upgrade.
BEGIN;
LOCK TABLE users IN ACCESS EXCLUSIVE MODE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS session_version integer NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS invitation_expires_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_hash text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires_at timestamptz;
-- Old verification JWTs have no invitation expiry and must not become invitations.
UPDATE users SET verification_token = NULL
WHERE invitation_expires_at IS NULL AND verification_token IS NOT NULL;
COMMIT;
