-- Dojo datasets are frozen copies of time series for offline comparison runs.
-- They never reference telemetry, so retention and catalogue edits leave them
-- unchanged.
CREATE TABLE IF NOT EXISTS dojo_datasets (
    id text PRIMARY KEY,
    name text NOT NULL,
    description text NOT NULL,
    origin text NOT NULL,
    source jsonb NOT NULL,
    created_by integer REFERENCES users(id) ON DELETE SET NULL,
    point_count integer NOT NULL,
    start_at timestamptz,
    end_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_dojo_dataset_origin CHECK (origin IN ('csv', 'history'))
);
CREATE TABLE IF NOT EXISTS dojo_dataset_series (
    id text PRIMARY KEY,
    dataset_id text NOT NULL REFERENCES dojo_datasets(id) ON DELETE CASCADE,
    position integer NOT NULL,
    name text NOT NULL,
    unit text,
    reading_id text,
    point_count integer NOT NULL,
    start_at timestamptz,
    end_at timestamptz,
    CONSTRAINT uq_dojo_series_name UNIQUE (dataset_id, name),
    CONSTRAINT uq_dojo_series_position UNIQUE (dataset_id, position)
);
CREATE TABLE IF NOT EXISTS dojo_dataset_points (
    -- No foreign key: a per-row check would slow large imports several
    -- times; the service deletes points together with their dataset.
    series_id text NOT NULL,
    timestamp timestamptz NOT NULL,
    value double precision NOT NULL,
    CONSTRAINT pk_dojo_point PRIMARY KEY (series_id, timestamp)
);
