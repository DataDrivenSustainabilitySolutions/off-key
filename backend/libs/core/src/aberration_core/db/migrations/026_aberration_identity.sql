-- Rename database-owned runtime identities after all old writers are stopped.
-- Migration 025 stays byte-for-byte immutable for existing checksum ledgers.
-- A transaction timestamp is not a commit cursor. Every evidence INSERT
-- reserves a monotonic watermark while holding this singleton row through
-- commit. Later writers wait, including transactions that began earlier.
CREATE TABLE IF NOT EXISTS monitoring_evidence_clock (
    id integer PRIMARY KEY,
    last_created timestamptz NOT NULL,
    CONSTRAINT ck_evidence_clock_singleton CHECK (id = 1)
);
-- statement
INSERT INTO monitoring_evidence_clock (id, last_created)
    SELECT 1, greatest(clock_timestamp(), coalesce(max(created), clock_timestamp()))
    FROM monitoring_evidence
    ON CONFLICT (id) DO NOTHING;
-- statement
CREATE OR REPLACE FUNCTION aberration_reserve_evidence_time()
RETURNS trigger AS $$
DECLARE stamp timestamptz;
BEGIN
    UPDATE monitoring_evidence_clock
       SET last_created = greatest(clock_timestamp(), last_created + interval '1 microsecond')
     WHERE id = 1 RETURNING last_created INTO STRICT stamp;
    PERFORM set_config('aberration.evidence_created', stamp::text, true);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
-- statement
CREATE OR REPLACE FUNCTION aberration_stamp_evidence()
RETURNS trigger AS $$
BEGIN
    NEW.created := current_setting('aberration.evidence_created')::timestamptz;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
-- statement
CREATE OR REPLACE TRIGGER trg_evidence_reserve_time
BEFORE INSERT ON monitoring_evidence FOR EACH STATEMENT
EXECUTE FUNCTION aberration_reserve_evidence_time();
-- statement
CREATE OR REPLACE TRIGGER trg_evidence_stamp
BEFORE INSERT ON monitoring_evidence FOR EACH ROW
EXECUTE FUNCTION aberration_stamp_evidence();

-- The normal schema reconciliation installs the new anomaly trigger afterwards.
DROP TRIGGER IF EXISTS trg_anomaly_identity_sync ON anomalies;
DROP FUNCTION IF EXISTS off_key_sync_anomaly_identity();
DROP FUNCTION IF EXISTS off_key_reserve_evidence_time();
DROP FUNCTION IF EXISTS off_key_stamp_evidence();

-- Job records refer to procedure names. Remove the old jobs before dropping
-- their procedures; normal policy reconciliation creates the new jobs using
-- the current configured retention and cap. No telemetry is deleted here.
DO $$
DECLARE old_job record;
BEGIN
    FOR old_job IN
        SELECT job_id FROM timescaledb_information.jobs
        WHERE proc_schema = 'public'
          AND proc_name IN ('off_key_anomaly_retention', 'off_key_storage_cap')
    LOOP
        PERFORM delete_job(old_job.job_id);
    END LOOP;
END;
$$;
DROP PROCEDURE IF EXISTS public.off_key_anomaly_retention(integer, jsonb);
DROP PROCEDURE IF EXISTS public.off_key_storage_cap(integer, jsonb);

-- A coordinated maintenance cutover deliberately starts fresh authentication
-- and detector calibration. Old signed/pickled state must not be interpreted
-- under the new package and signing-domain identities. Evidence is retained.
DELETE FROM remembered_sessions;
DELETE FROM radar_runtime_checkpoints;
