-- Keep historical/manual anomalies and their public IDs in the empty scope.
-- A monitor's identity distinguishes concurrent multivariate alarms even when
-- their entity, observation timestamp and telemetry marker are identical.
ALTER TABLE anomalies ADD COLUMN IF NOT EXISTS service_id text NOT NULL DEFAULT '';
ALTER TABLE anomaly_identity ADD COLUMN IF NOT EXISTS service_id text NOT NULL DEFAULT '';

ALTER TABLE anomaly_identity DROP CONSTRAINT fk_anomaly_identity_anomaly;
ALTER TABLE anomaly_identity DROP CONSTRAINT uq_anomaly_identity_target;
ALTER TABLE anomalies DROP CONSTRAINT pk_anomaly;

ALTER TABLE anomalies ADD CONSTRAINT pk_anomaly
    PRIMARY KEY (charger_id, timestamp, telemetry_type, service_id);
ALTER TABLE anomaly_identity ADD CONSTRAINT uq_anomaly_identity_target
    UNIQUE (charger_id, timestamp, telemetry_type, service_id);
ALTER TABLE anomaly_identity ADD CONSTRAINT fk_anomaly_identity_anomaly
    FOREIGN KEY (charger_id, timestamp, telemetry_type, service_id)
    REFERENCES anomalies (charger_id, timestamp, telemetry_type, service_id)
    ON DELETE CASCADE;
