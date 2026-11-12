CREATE TABLE IF NOT EXISTS alarm_deletions (
    id text PRIMARY KEY,
    alarm_ids text[] NOT NULL,
    count integer NOT NULL,
    expires_at timestamptz NOT NULL,
    deleted_count integer
);
CREATE INDEX IF NOT EXISTS ix_alarm_deletions_expires_at ON alarm_deletions (expires_at);
