-- Run with psql -v ON_ERROR_STOP=1 before deploying durable collection pauses.
BEGIN;
ALTER TABLE services ADD COLUMN IF NOT EXISTS stop_requested_at timestamptz;

-- Repair payloads written by the former collection pause path.
UPDATE services
SET operational_status = (operational_status::jsonb - 'message') ||
    jsonb_build_object('detail', COALESCE(
        operational_status::jsonb -> 'detail', operational_status::jsonb -> 'message'
    ))
WHERE operational_status::jsonb ? 'message';
COMMIT;
