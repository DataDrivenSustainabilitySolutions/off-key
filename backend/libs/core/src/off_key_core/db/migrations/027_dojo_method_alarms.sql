-- A Dojo run can try other calibration methods on its own detector scores.
-- Each result keeps which of them would have alarmed: one bit per method, in
-- the order the run's settings name them.
-- Null where a run compares no methods, or was still learning.
ALTER TABLE dojo_run_results
    ADD COLUMN IF NOT EXISTS method_alarms bigint;
