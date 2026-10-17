"""Heartbeat receipt evidence and checkpoint fencing in one atomic status write."""

from sqlalchemy import text

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
