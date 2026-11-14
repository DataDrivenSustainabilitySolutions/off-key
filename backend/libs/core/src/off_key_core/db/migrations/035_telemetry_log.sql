-- Stored telemetry becomes the log RADAR reads: every new row takes the next
-- position, in the order its writer commits. A monitor saves the position it
-- has processed with its checkpoint and replays from there after a restart.
-- Earlier rows keep no position; no monitor reads from before this release.
CREATE SEQUENCE IF NOT EXISTS telemetry_log_seq AS bigint;
ALTER TABLE telemetry ADD COLUMN IF NOT EXISTS log_seq bigint;
ALTER TABLE telemetry ALTER COLUMN log_seq SET DEFAULT nextval('telemetry_log_seq');
CREATE INDEX IF NOT EXISTS ix_telemetry_log ON telemetry (charger_id, type, log_seq);

-- Monitors no longer connect to the broker, so stored launches carry no
-- broker options.
UPDATE services
SET launch_config = (launch_config::jsonb - 'mqtt_config')::json
WHERE launch_config IS NOT NULL AND launch_config::jsonb ? 'mqtt_config';

UPDATE monitoring_pipeline_runs
SET launch_config = launch_config - 'mqtt_config'
WHERE launch_config ? 'mqtt_config';

UPDATE monitoring_pipeline_activations
SET launch_config = launch_config - 'mqtt_config'
WHERE launch_config ? 'mqtt_config';

-- A snapshot now holds the log position its state covers. Earlier snapshots
-- hold none, so their monitors learn afresh from the newest logged reading.
DELETE FROM radar_runtime_checkpoints;
