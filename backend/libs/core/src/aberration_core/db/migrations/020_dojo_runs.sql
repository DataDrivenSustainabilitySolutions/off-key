-- Dojo runs replay one detection design over one dataset, outside Monitoring.
-- A worker claims queued runs; results are kept until the run is deleted.
CREATE TABLE IF NOT EXISTS dojo_runs (
    id text PRIMARY KEY,
    dataset_id text NOT NULL REFERENCES dojo_datasets(id) ON DELETE CASCADE,
    name text NOT NULL,
    status text NOT NULL,
    config jsonb NOT NULL,
    cancel_requested boolean NOT NULL,
    points_total bigint NOT NULL,
    points_read bigint NOT NULL,
    result_count bigint NOT NULL,
    alarm_count bigint NOT NULL,
    stats jsonb NOT NULL,
    error text,
    worker text,
    created_by integer REFERENCES users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    heartbeat_at timestamptz,
    finished_at timestamptz,
    CONSTRAINT ck_dojo_run_status
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);
CREATE INDEX IF NOT EXISTS ix_dojo_runs_status ON dojo_runs (status, created_at);
CREATE INDEX IF NOT EXISTS ix_dojo_runs_dataset ON dojo_runs (dataset_id);
CREATE TABLE IF NOT EXISTS dojo_run_results (
    -- No foreign key, as for dataset points: the service deletes a run's
    -- results together with the run.
    run_id text NOT NULL,
    sequence bigint NOT NULL,
    timestamp timestamptz NOT NULL,
    phase text NOT NULL,
    score double precision,
    threshold double precision,
    alarm boolean NOT NULL,
    CONSTRAINT pk_dojo_run_result PRIMARY KEY (run_id, sequence)
);
