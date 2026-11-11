-- Each inference keeps what its forecaster steps expected of the observation:
-- the forecast made for it and the calibrated interval around it, so charts
-- can draw the band the value was compared with.
-- Rows written before this migration keep an empty list.
ALTER TABLE monitoring_evidence
    ADD COLUMN IF NOT EXISTS forecasts jsonb NOT NULL DEFAULT '[]'::jsonb;
