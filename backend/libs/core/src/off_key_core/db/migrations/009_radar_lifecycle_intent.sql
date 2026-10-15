-- Reserve monitoring inputs before asking Docker to create a worker. Runtime
-- admission fences delayed create requests after a stop, deletion or replacement.
ALTER TABLE services ADD COLUMN IF NOT EXISTS desired_state text NOT NULL DEFAULT 'running';
ALTER TABLE services ADD COLUMN IF NOT EXISTS lifecycle_version integer NOT NULL DEFAULT 1;
ALTER TABLE services ADD COLUMN IF NOT EXISTS config_fingerprint text;
ALTER TABLE services ADD COLUMN IF NOT EXISTS collection_fingerprint text;
UPDATE services SET desired_state = 'stopped' WHERE NOT status;
