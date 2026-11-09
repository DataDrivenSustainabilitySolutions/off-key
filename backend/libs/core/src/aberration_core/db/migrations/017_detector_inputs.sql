-- Each inference keeps the features its detectors scored, after every step
-- before them, so charts can show derived features such as phase deviations.
-- Rows written before this migration keep an empty list.
ALTER TABLE monitoring_evidence
    ADD COLUMN IF NOT EXISTS detector_inputs jsonb NOT NULL DEFAULT '[]'::jsonb;
