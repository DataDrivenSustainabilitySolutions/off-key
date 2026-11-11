CREATE TABLE IF NOT EXISTS revoked_access_tokens (
    token_hash text PRIMARY KEY,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_revoked_access_tokens_expiry
    ON revoked_access_tokens (expires_at);
