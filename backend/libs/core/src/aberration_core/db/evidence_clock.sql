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
