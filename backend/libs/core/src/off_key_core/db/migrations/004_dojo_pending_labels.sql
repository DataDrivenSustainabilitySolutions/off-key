-- Members and agents can propose labels, by a condition over the series or as
-- intervals, which wait for a member's review and score no run until added.
-- A label added from one keeps the rule that found it and the agent's name.
ALTER TABLE dojo_dataset_labels ADD COLUMN IF NOT EXISTS rule text NOT NULL DEFAULT '';
ALTER TABLE dojo_dataset_labels ADD COLUMN IF NOT EXISTS suggested_by_agent text;
CREATE TABLE IF NOT EXISTS dojo_pending_labels (
    id text PRIMARY KEY,
    dataset_id text NOT NULL REFERENCES dojo_datasets (id) ON DELETE CASCADE,
    start_at timestamp with time zone NOT NULL,
    end_at timestamp with time zone NOT NULL,
    note text NOT NULL,
    rule text NOT NULL,
    created_by integer REFERENCES users (id) ON DELETE SET NULL,
    created_by_agent text,
    created_by_agent_id integer,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT ck_dojo_pending_label_interval CHECK (end_at > start_at)
);
CREATE INDEX IF NOT EXISTS ix_dojo_pending_labels_dataset
    ON dojo_pending_labels (dataset_id, start_at);
