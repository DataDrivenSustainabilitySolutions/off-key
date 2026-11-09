CREATE TABLE IF NOT EXISTS remembered_sessions (
    token_hash text PRIMARY KEY,
    user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_version integer NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_remembered_sessions_user_id ON remembered_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_remembered_sessions_expires_at ON remembered_sessions (expires_at);
