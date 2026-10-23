-- Drop schema nothing reads any more. Fresh databases never had these objects,
-- so every statement tolerates their absence.
-- RADAR metrics rows and file-era checkpoints (runtime-created, never read).
DROP TABLE IF EXISTS radar_service_metrics;
DROP TABLE IF EXISTS radar_model_checkpoints;
-- The model catalogue is served from code.
DROP TABLE IF EXISTS model_registry;
-- Kubernetes-era column, never written.
ALTER TABLE services DROP COLUMN IF EXISTS stateful_set_name;
-- Telemetry indexes no query uses. The primary key serves upserts and the
-- remaining composites serve the history and cursor reads; TimescaleDB keeps
-- its own time index.
ALTER TABLE telemetry DROP CONSTRAINT IF EXISTS uq_telemetry_entry;
DROP INDEX IF EXISTS ix_telemetry_charger_id;
DROP INDEX IF EXISTS ix_telemetry_timestamp;
DROP INDEX IF EXISTS ix_telemetry_value;
DROP INDEX IF EXISTS ix_telemetry_type;
DROP INDEX IF EXISTS ix_telemetry_data_source;
DROP INDEX IF EXISTS ix_telemetry_created;
DROP INDEX IF EXISTS ix_telemetry_charger_timestamp;
DROP INDEX IF EXISTS ix_telemetry_charger_type;
DROP INDEX IF EXISTS ix_telemetry_timestamp_desc;
