-- A policy can combine several detectors; each inference keeps every detector's
-- score and surprise, so an alarm names the detector that drove it. Rows of a
-- single detector keep an empty list.
ALTER TABLE monitoring_evidence
    ADD COLUMN IF NOT EXISTS detector_results jsonb NOT NULL DEFAULT '[]'::jsonb;
