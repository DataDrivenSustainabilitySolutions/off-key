-- Each refresh replaces the browser secret; a family groups one sign-in's secrets.
ALTER TABLE remembered_sessions ADD COLUMN IF NOT EXISTS family_id text;
UPDATE remembered_sessions SET family_id = token_hash WHERE family_id IS NULL;
ALTER TABLE remembered_sessions ALTER COLUMN family_id SET NOT NULL;
ALTER TABLE remembered_sessions ADD COLUMN IF NOT EXISTS replaced_at timestamptz;
CREATE INDEX IF NOT EXISTS ix_remembered_sessions_family_id ON remembered_sessions (family_id);
