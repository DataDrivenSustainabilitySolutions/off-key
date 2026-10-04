ALTER TABLE services ADD COLUMN launch_config json;
CREATE TABLE deployment_maintenance (
    id integer PRIMARY KEY,
    revision text NOT NULL,
    phase text NOT NULL,
    monitors jsonb NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT deployment_maintenance_singleton CHECK (id = 1)
);
