ALTER TABLE dojo_runs ADD COLUMN IF NOT EXISTS metrics_cache jsonb NOT NULL DEFAULT '{}';
