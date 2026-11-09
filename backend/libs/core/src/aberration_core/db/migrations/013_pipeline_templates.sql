-- Reusable templates are explicit; applied configurations retain private provenance.
ALTER TABLE monitoring_pipelines
    ADD COLUMN is_template boolean NOT NULL DEFAULT true;
