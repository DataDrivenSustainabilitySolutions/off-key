-- Signed monitor recovery snapshots survive task and node replacement. The
-- obsolete path-only radar_model_checkpoints auxiliary table remains untouched.
CREATE TABLE IF NOT EXISTS radar_runtime_checkpoints (
    service_id text PRIMARY KEY,
    format_version integer NOT NULL,
    configuration_fingerprint text NOT NULL,
    runtime_fingerprint text NOT NULL,
    processed_count bigint NOT NULL,
    saved_at timestamptz NOT NULL,
    payload bytea NOT NULL,
    signature text NOT NULL,
    CONSTRAINT fk_radar_checkpoint_service FOREIGN KEY (service_id)
        REFERENCES services(id) ON DELETE CASCADE,
    CONSTRAINT ck_radar_checkpoint_count CHECK (processed_count >= 0)
);
