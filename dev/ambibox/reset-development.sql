-- One-time clean break from local charger IDs to catalog UUIDs.
-- Stop collection workers and all managed RADAR workloads before running.
-- User accounts and the model registry are preserved. No telemetry is retained.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout = '5s';
DO $$
DECLARE
    lock_key bigint;
BEGIN
    FOREACH lock_key IN ARRAY ARRAY[73128001, 73128002, 73128003] LOOP
        IF NOT pg_try_advisory_xact_lock(lock_key) THEN
            RAISE EXCEPTION 'Stop catalog editing and collection workers before reset';
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM services WHERE status = true) THEN
        RAISE EXCEPTION 'Stop managed monitors through the application before reset';
    END IF;
END $$;
TRUNCATE collection_state, collection_bindings, collection_configuration,
    collection_revisions, mqtt_topics, services, favorites, telemetry, anomalies,
    monitoring_evidence, anomaly_identity, chargers RESTART IDENTITY;
COMMIT;
