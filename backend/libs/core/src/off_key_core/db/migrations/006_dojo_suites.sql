-- A benchmark suite fixes a list of labelled datasets to test designs on
-- again and again; its datasets never change, so its studies stay
-- comparable. A study replays one design over every dataset of a suite, one
-- run each. Its runs are ordinary runs that name it.
CREATE TABLE IF NOT EXISTS dojo_suites (
    id text PRIMARY KEY,
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    derived_from text REFERENCES dojo_suites (id) ON DELETE SET NULL,
    created_by integer REFERENCES users (id) ON DELETE SET NULL,
    created_by_agent text,
    created_by_agent_id integer,
    reviewed_by integer REFERENCES users (id) ON DELETE SET NULL,
    reviewed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS dojo_suite_datasets (
    suite_id text NOT NULL REFERENCES dojo_suites (id) ON DELETE CASCADE,
    dataset_id text NOT NULL REFERENCES dojo_datasets (id) ON DELETE RESTRICT,
    position integer NOT NULL,
    PRIMARY KEY (suite_id, dataset_id)
);
CREATE INDEX IF NOT EXISTS ix_dojo_suite_datasets_dataset
    ON dojo_suite_datasets (dataset_id);
CREATE TABLE IF NOT EXISTS dojo_studies (
    id text PRIMARY KEY,
    suite_id text NOT NULL REFERENCES dojo_suites (id) ON DELETE CASCADE,
    name text NOT NULL,
    config jsonb NOT NULL,
    created_by integer REFERENCES users (id) ON DELETE SET NULL,
    created_by_agent_id integer,
    created_at timestamp with time zone NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_dojo_studies_suite ON dojo_studies (suite_id, created_at);
ALTER TABLE dojo_runs ADD COLUMN IF NOT EXISTS study_id text
    REFERENCES dojo_studies (id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_dojo_runs_study ON dojo_runs (study_id);
