-- Add the domain-neutral catalogue without rewriting legacy bindings or history.
-- IF NOT EXISTS also supports development installations that used create_all.
CREATE TABLE IF NOT EXISTS system_configuration (
    id integer PRIMARY KEY,
    revision integer NOT NULL,
    document jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL,
    CONSTRAINT system_singleton CHECK (id = 1)
);
CREATE TABLE IF NOT EXISTS system_revisions (
    revision integer PRIMARY KEY,
    document jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL
);
CREATE TABLE IF NOT EXISTS system_collection_configuration (
    id integer PRIMARY KEY,
    revision integer NOT NULL,
    document jsonb NOT NULL,
    ingress_status jsonb NOT NULL,
    collection_status jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL,
    CONSTRAINT system_collection_singleton CHECK (id = 1)
);
