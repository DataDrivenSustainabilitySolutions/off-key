-- Durable design revisions and runs must survive ephemeral service deletion.
CREATE TABLE monitoring_pipelines (
    id text PRIMARY KEY, name text NOT NULL, description text NOT NULL,
    archived boolean NOT NULL, version integer NOT NULL,
    draft jsonb NOT NULL, layout jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE monitoring_pipeline_revisions (
    id text PRIMARY KEY, pipeline_id text NOT NULL REFERENCES monitoring_pipelines(id),
    number integer NOT NULL, definition jsonb NOT NULL, fingerprint text NOT NULL,
    catalog_id text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_pipeline_revision_number UNIQUE (pipeline_id, number)
);
CREATE INDEX ix_monitoring_pipeline_revisions_pipeline_id ON monitoring_pipeline_revisions(pipeline_id);
CREATE TABLE monitoring_pipeline_runs (
    id text PRIMARY KEY, service_id text NOT NULL UNIQUE,
    revision_id text REFERENCES monitoring_pipeline_revisions(id),
    predecessor_run_id text REFERENCES monitoring_pipeline_runs(id),
    execution jsonb, launch_config jsonb NOT NULL, layout jsonb NOT NULL,
    binding_metadata jsonb,
    status text NOT NULL, error text, created_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz
);
CREATE TABLE monitoring_pipeline_activations (
    id text PRIMARY KEY, idempotency_key text NOT NULL UNIQUE, request_hash text NOT NULL,
    revision_id text NOT NULL REFERENCES monitoring_pipeline_revisions(id),
    service_id text NOT NULL UNIQUE, run_id text NOT NULL REFERENCES monitoring_pipeline_runs(id),
    predecessor_service_id text, predecessor_lifecycle_version integer,
    retirement_started boolean NOT NULL, heartbeat_deadline timestamptz,
    phase text NOT NULL, claim_topics jsonb NOT NULL,
    collection_fingerprint text NOT NULL, launch_config jsonb NOT NULL, preflight jsonb,
    image_digest text, error text, cancel_requested boolean NOT NULL,
    controller_token text, lease_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_monitoring_pipeline_activations_phase ON monitoring_pipeline_activations(phase);
