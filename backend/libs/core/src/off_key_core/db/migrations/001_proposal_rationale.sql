-- A proposal says why it is worth running in four short fields (what it
-- watches, why this design, the evidence, its limits), which the monitor keeps
-- once a member starts it. Proposals made before have none.
ALTER TABLE monitoring_pipeline_proposals ADD COLUMN IF NOT EXISTS rationale jsonb;
