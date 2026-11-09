-- Dojo labels mark known problems as time intervals on a dataset. Run metrics
-- read them at request time, so editing a label never requires a replay.
CREATE TABLE IF NOT EXISTS dojo_dataset_labels (
    id text PRIMARY KEY,
    dataset_id text NOT NULL REFERENCES dojo_datasets(id) ON DELETE CASCADE,
    start_at timestamptz NOT NULL,
    end_at timestamptz NOT NULL,
    note text NOT NULL,
    created_by integer REFERENCES users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_dojo_label_interval CHECK (end_at > start_at)
);
CREATE INDEX IF NOT EXISTS ix_dojo_labels_dataset
    ON dojo_dataset_labels (dataset_id, start_at);
