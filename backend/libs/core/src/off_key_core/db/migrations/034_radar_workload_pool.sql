-- RADAR runs in a pool of workers that lease workloads from this table instead
-- of one Swarm service per monitor. Existing per-monitor services are retired by
-- the release; their monitors start again from the pool.
CREATE TABLE IF NOT EXISTS radar_workloads (
    id text PRIMARY KEY,
    name text NOT NULL UNIQUE,
    kind text NOT NULL,
    labels jsonb NOT NULL DEFAULT '{}'::jsonb,
    runtime text NOT NULL,
    module text NOT NULL,
    environment jsonb NOT NULL DEFAULT '{}'::jsonb,
    memory_limit_bytes bigint,
    restart boolean NOT NULL DEFAULT false,
    desired text NOT NULL DEFAULT 'run',
    state text NOT NULL DEFAULT 'pending',
    worker_id text,
    lease_expires_at timestamptz,
    not_before timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    exit_code integer,
    detail text,
    crashes jsonb NOT NULL DEFAULT '[]'::jsonb,
    output text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_radar_workloads_kind CHECK (kind IN ('monitor', 'preflight')),
    CONSTRAINT ck_radar_workloads_desired CHECK (desired IN ('run', 'stop')),
    CONSTRAINT ck_radar_workloads_state CHECK (
        state IN ('pending', 'running', 'complete', 'failed', 'shutdown')
    ),
    CONSTRAINT ck_radar_workloads_lease CHECK (
        (state = 'running') = (worker_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS ix_radar_workloads_claim ON radar_workloads (runtime, state, created_at);
CREATE INDEX IF NOT EXISTS ix_radar_workloads_worker ON radar_workloads (worker_id);
