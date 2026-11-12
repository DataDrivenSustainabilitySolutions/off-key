-- A Mute alarms step keeps the alarm of an observation from being raised while
-- its condition holds. The evidence keeps such an alarm as muted: alarm stays
-- false and muted is true, so a review shows what the step held back.
-- Rows written before this migration were never muted.
ALTER TABLE monitoring_evidence
    ADD COLUMN IF NOT EXISTS muted boolean NOT NULL DEFAULT false;
