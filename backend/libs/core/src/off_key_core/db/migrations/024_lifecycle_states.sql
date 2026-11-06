-- Name the lifecycle states the services, runs and activations may hold, and
-- record when an activation entered its phase so each phase can time out.
-- Every value written since migrations 009 and 010 is in these lists.
-- Repeatable, so a database that already has the checks keeps them.
ALTER TABLE monitoring_pipeline_activations
    ADD COLUMN IF NOT EXISTS phase_entered_at timestamptz;
UPDATE monitoring_pipeline_activations
    SET phase_entered_at = updated_at WHERE phase_entered_at IS NULL;
ALTER TABLE monitoring_pipeline_activations
    ALTER COLUMN phase_entered_at SET DEFAULT now(),
    ALTER COLUMN phase_entered_at SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'services'::regclass AND conname = 'ck_services_desired_state'
    ) THEN
        ALTER TABLE services ADD CONSTRAINT ck_services_desired_state
            CHECK (desired_state IN ('running', 'stopped', 'deleted'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'monitoring_pipeline_runs'::regclass
            AND conname = 'ck_pipeline_run_status'
    ) THEN
        ALTER TABLE monitoring_pipeline_runs ADD CONSTRAINT ck_pipeline_run_status
            CHECK (status IN (
                'reserved', 'starting', 'running', 'stopped', 'failed', 'cancelled'
            ));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'monitoring_pipeline_activations'::regclass
            AND conname = 'ck_pipeline_activation_phase'
    ) THEN
        ALTER TABLE monitoring_pipeline_activations
            ADD CONSTRAINT ck_pipeline_activation_phase
            CHECK (phase IN (
                'requested', 'preflighting', 'validated', 'retiring', 'starting',
                'awaiting_heartbeat', 'succeeded', 'cancelling', 'cancelled', 'failed'
            ));
    END IF;
END $$;
