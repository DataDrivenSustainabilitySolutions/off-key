-- A block is a named chain of steps that the composer copies into a design.
-- A design keeps no reference to the block its steps came from, so deleting a
-- block changes no design, revision or run.
CREATE TABLE IF NOT EXISTS monitoring_pipeline_blocks (
    id text PRIMARY KEY,
    name text NOT NULL,
    description text NOT NULL,
    steps jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_pipeline_block_name UNIQUE (name)
);
