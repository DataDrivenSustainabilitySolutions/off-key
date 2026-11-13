-- Monitors and Dojo runs stop using freshness and skew windows: each reading's
-- last value now counts for a multiple of its own learned interval. Remove the
-- retired settings so stored launches and statuses read with the new defaults.
UPDATE services
SET launch_config = (
    launch_config::jsonb
    #- '{performance_config,sensor_freshness_seconds}'
    #- '{performance_config,observation_max_age_seconds}'
    #- '{performance_config,observation_future_tolerance_seconds}'
    #- '{performance_config,alignment_max_skew_seconds}'
)::json
WHERE launch_config IS NOT NULL
    AND jsonb_typeof(launch_config::jsonb -> 'performance_config') = 'object';

UPDATE services
SET operational_status = operational_status::jsonb #- '{activity,freshness_seconds}'
WHERE operational_status::jsonb #> '{activity,freshness_seconds}' IS NOT NULL;

UPDATE monitoring_pipeline_runs
SET launch_config = launch_config
    #- '{performance_config,sensor_freshness_seconds}'
    #- '{performance_config,observation_max_age_seconds}'
    #- '{performance_config,observation_future_tolerance_seconds}'
    #- '{performance_config,alignment_max_skew_seconds}'
WHERE jsonb_typeof(launch_config -> 'performance_config') = 'object';

UPDATE monitoring_pipeline_runs
SET final_status = final_status #- '{activity,freshness_seconds}'
WHERE final_status #> '{activity,freshness_seconds}' IS NOT NULL;

UPDATE monitoring_pipeline_activations
SET launch_config = launch_config
    #- '{performance_config,sensor_freshness_seconds}'
    #- '{performance_config,observation_max_age_seconds}'
    #- '{performance_config,observation_future_tolerance_seconds}'
    #- '{performance_config,alignment_max_skew_seconds}'
WHERE jsonb_typeof(launch_config -> 'performance_config') = 'object';

UPDATE dojo_runs
SET config = jsonb_set(config, '{alignment}', '{}'::jsonb)
WHERE config ? 'alignment';
