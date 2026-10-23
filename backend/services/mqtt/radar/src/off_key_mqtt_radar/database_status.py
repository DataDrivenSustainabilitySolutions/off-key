"""Status and fencing statements RADAR runs against shared service rows."""

from sqlalchemy import text

# A failed or ended Run fences its service: no admission, no status publication.
TERMINAL_RUN = "(status = 'failed' OR ended_at IS NOT NULL)"

TERMINAL_RUN_EXISTS = text(
    "SELECT EXISTS (SELECT 1 FROM monitoring_pipeline_runs "
    f"WHERE service_id = :service_id AND {TERMINAL_RUN})"
)

LOCK_SERVICE_ROW = text(
    "SELECT id FROM services WHERE id = :service_id FOR NO KEY UPDATE"
)

FAIL_PIPELINE_RUN = text(
    "UPDATE monitoring_pipeline_runs SET status = 'failed', "
    "error = :error, ended_at = now() "
    "WHERE id = :run_id AND service_id = :service_id"
)

FAIL_SERVICE_STATUS = text(
    "UPDATE services SET operational_stage = 'failed', "
    "operational_status = CAST(:status AS jsonb), "
    "operational_updated_at = now() "
    "WHERE id = :service_id"
)

# Heartbeat receipt evidence and checkpoint fencing in one atomic status write.

HEARTBEAT_UPDATE = text("""
    UPDATE services
    SET operational_stage = :stage,
        operational_status = CAST(:status_payload AS jsonb) ||
            CASE WHEN :stage NOT IN ('failed', 'stopped') THEN
                jsonb_build_object('first_heartbeat_at', COALESCE(
                    NULLIF(operational_status->'first_heartbeat_at', 'null'::jsonb),
                    to_jsonb(clock_timestamp())
                ))
            ELSE '{}'::jsonb END,
        operational_updated_at = :updated_at
    WHERE id = :service_id
        AND (NOT :managed OR EXISTS (
            SELECT 1 FROM radar_runtime_checkpoints
            WHERE service_id = :service_id
                AND signature IN (:signature, :pending_signature)
        ))
""")
