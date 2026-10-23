/**
 * Types for monitoring and anomaly detection
 *
 * Replaces Record<string, any> usage in Monitoring.tsx
 */

// Parameter schema from the static model registry
export type MonitoringStrategy = 'static_baseline' | 'adaptive_stream';

type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export interface ParameterSchema {
  type?: 'string' | 'number' | 'integer' | 'boolean' | 'array' | 'object' | 'null';
  description?: string;
  default?: JsonValue;
  minimum?: number;
  maximum?: number;
  enum?: JsonPrimitive[];
  anyOf?: ParameterSchema[];
  items?: ParameterSchema;
  prefixItems?: ParameterSchema[];
  minItems?: number;
  maxItems?: number;
  properties?: Record<string, ParameterSchema>;
  required?: string[];
  'x-aberrant-component-kind'?: string;
}

export interface ModelCapabilities {
  event_kind: string;
  feature_count: { minimum: number; maximum: number | null };
  score_kind: string;
  higher_is_more_anomalous: boolean | null;
  warmup: { minimum: number | null; unit: string };
  state: string;
  requires_unit_interval: boolean;
}

// Model definition from registry API
export interface ModelDefinition {
  parameters: {
    properties: Record<string, ParameterSchema>;
    required?: string[];
  };
  description?: string;
  name?: string;
  family?: string;
  strategy?: string;
  default_parameters?: Record<string, JsonValue>;
  catalog_id?: string | null;
  algorithm_family?: string | null;
  available?: boolean;
  default_capabilities?: ModelCapabilities | null;
}

// Active monitoring service
export type OperationalStage =
  | 'starting'
  | 'waiting_for_data'
  | 'collecting_training'
  | 'collecting_calibration'
  | 'training'
  | 'operational'
  | 'degraded'
  | 'failed'
  | 'stopped';

interface OperationalProgress {
  current: number;
  target: number;
}

interface MonitoringCoverage {
  delivery: 'best_effort';
  has_gaps: boolean;
  received_message_count: number;
  dropped_message_count: number;
  dropped_by_reason: Record<string, number>;
  possible_gap_count: number;
  last_gap_at?: string | null;
  last_gap_reason?: string | null;
}

interface MonitoringActivity {
  freshness_seconds: number;
  last_input_at?: string | null;
  last_processed_at?: string | null;
  last_inference_at?: string | null;
  last_persisted_at?: string | null;
  missing_sensors: string[];
  stale_sensors: string[];
  inputs_stalled: boolean;
  inference_stalled: boolean;
  persistence_stalled: boolean;
}

export interface OperationalStatus {
  stage: OperationalStage;
  detail?: string | null;
  progress?: OperationalProgress | null;
  message_count: number;
  processed_message_count: number;
  last_alignment_status?: string | null;
  error?: string | null;
  updated_at?: string | null;
  is_stale: boolean;
  coverage?: MonitoringCoverage;
  activity?: MonitoringActivity;
}

export interface ActiveService {
  id: string;
  container_id: string;
  container_name: string;
  display_name?: string | null;
  mqtt_topics: string[];
  status: boolean;
  operational_status: OperationalStatus;
  docker_status?: string;
  monitoring_strategy?: MonitoringStrategy | null;
  model_type?: string;
  created_at?: string;
}

interface MonitoringPerformanceConfig {
  sensor_key_strategy: 'full_hierarchy' | 'top_level' | 'leaf';
  sensor_freshness_seconds: number;
  observation_max_age_seconds?: number;
  observation_future_tolerance_seconds?: number;
  alignment_max_skew_seconds?: number;
}

export type MartingaleBettingFunction =
  | 'power'
  | 'simple_mixture'
  | 'simple_jumper';

export type MartingaleAlarmStatistic =
  | 'martingale'
  | 'restarted_martingale'
  | 'cusum'
  | 'shiryaev_roberts';

interface MartingaleTrackerBase {
  tracker_id: string;
  alarm_statistic: MartingaleAlarmStatistic;
  threshold_config:
    | { mode: 'manual'; value: number }
    | { mode: 'automatic' };
}

interface PowerMartingaleTracker extends MartingaleTrackerBase {
  betting_function: 'power';
  epsilon: number;
}

interface SimpleMixtureMartingaleTracker extends MartingaleTrackerBase {
  betting_function: 'simple_mixture';
  epsilons?: number[] | null;
  n_grid: number;
  min_epsilon: number;
}

interface SimpleJumperMartingaleTracker extends MartingaleTrackerBase {
  betting_function: 'simple_jumper';
  jump: number;
}

export type MartingaleTrackerConfig =
  | PowerMartingaleTracker
  | SimpleMixtureMartingaleTracker
  | SimpleJumperMartingaleTracker;

interface StaticMartingaleConfig {
  trackers: MartingaleTrackerConfig[];
  automatic_threshold_calibration: {
    false_alarm_probability: number;
    horizon: number;
    simulation_count: number;
  };
}

interface StaticBaselineRequestConfig {
  model_type: string;
  model_params: Record<string, JsonValue>;
  training_window_size: number;
  calibration_window_size: number;
  conformal_strategy: 'split';
  martingale_config: StaticMartingaleConfig;
}

export type AdaptivePreprocessingStep =
  | { type: 'standard_scaler'; with_std: boolean }
  | { type: 'min_max_scaler'; feature_range: [number, number] }
  | {
      type: 'incremental_pca';
      n_components: number;
      n0: number;
      tol: number;
      forgetting_factor: number | null;
    }
  | { type: 'random_projection'; n_components: number; seed: number | null };

interface AdaptiveStreamRequestConfig {
  model_type: string;
  model_params: Record<string, JsonValue>;
  training_window_size: number;
  calibration_window_size: number;
  preprocessing_steps: AdaptivePreprocessingStep[];
  threshold_config: { mode: 'calibrated_quantile'; quantile: number };
}

// Anomaly detection request payload
interface AnomalyDetectionRequestBase {
  container_name: string;
  display_name?: string;
  service_type: 'radar';
  mqtt_topics: string[];
  model_type: string;
  model_params: Record<string, JsonValue>;
  performance_config: MonitoringPerformanceConfig;
}

export interface StaticAnomalyDetectionRequest extends AnomalyDetectionRequestBase {
  strategy: 'static_baseline';
  static_baseline_config: StaticBaselineRequestConfig;
}

export interface AdaptiveAnomalyDetectionRequest extends AnomalyDetectionRequestBase {
  strategy: 'adaptive_stream';
  adaptive_stream_config: AdaptiveStreamRequestConfig;
}

export type MonitoringStartRequest =
  | StaticAnomalyDetectionRequest
  | AdaptiveAnomalyDetectionRequest;

// Compatibility name retained for existing static-lane consumers.
export type AnomalyDetectionRequest = StaticAnomalyDetectionRequest;

interface MonitoringEvidence {
  service_id: string;
  timestamp: string;
  sequence_number: number;
  charger_id: string;
  sensor_set: string[];
  input_timestamps: Record<string, string>;
  strategy: MonitoringStrategy;
  model_type: string | null;
  p_value: number | null;
  anomaly_score: number | null;
  e_value: number | null;
  e_value_is_infinite: boolean;
  log_e_value: number | null;
  restarted_martingale: number | null;
  restarted_martingale_is_infinite: boolean;
  log_restarted_martingale: number | null;
  tracker_results?: MartingaleTrackerResult[];
  threshold: number;
  alarm: boolean;
}

interface MartingaleStatisticEvidence {
  value: number | null;
  is_infinite: boolean;
  log_value: number | null;
}

export interface MartingaleTrackerResult {
  tracker_id: string;
  betting_function: MartingaleBettingFunction;
  betting_parameters: Record<string, unknown>;
  alarm_statistic: MartingaleAlarmStatistic;
  statistic_value: number | null;
  statistic_is_infinite: boolean;
  log_statistic_value: number | null;
  statistics: Partial<
    Record<MartingaleAlarmStatistic, MartingaleStatisticEvidence>
  >;
  e_value: number | null;
  e_value_is_infinite: boolean;
  log_e_value: number | null;
  threshold: number;
  threshold_horizon?: number | null;
  threshold_window_position?: number | null;
  threshold_window_reset?: boolean;
  alarm_fired: boolean;
  alarm_active: boolean;
  alarm_count: number;
  tested_count: number;
}

export type MonitoringChartEvidence = Pick<
  MonitoringEvidence,
  | 'service_id'
  | 'timestamp'
  | 'sequence_number'
  | 'sensor_set'
  | 'input_timestamps'
  | 'restarted_martingale'
  | 'tracker_results'
  | 'threshold'
  | 'alarm'
> & {
  created: string;
  strategy?: MonitoringStrategy;
  model_type?: string | null;
  anomaly_score?: number | null;
};

export type MonitoringEvidenceCursor = Pick<
  MonitoringChartEvidence,
  'created' | 'timestamp' | 'service_id' | 'sequence_number'
>;

// Model parameters (cleaned for API submission)
export type ModelParams = Record<string, JsonValue>;
