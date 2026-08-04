/**
 * Types for monitoring and anomaly detection
 *
 * Replaces Record<string, any> usage in Monitoring.tsx
 */

// Parameter schema from the static model registry
export type MonitoringStrategy = 'static_baseline' | 'adaptive_stream';

export type JsonPrimitive = string | number | boolean | null;
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

export interface OperationalProgress {
  current: number;
  target: number;
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
}

export interface ActiveService {
  id: string;
  container_id: string;
  container_name: string;
  mqtt_topics: string[];
  status: boolean;
  operational_status: OperationalStatus;
  docker_status?: string;
  monitoring_strategy?: string;
  model_type?: string;
  created_at?: string;
}

export interface MonitoringPerformanceConfig {
  sensor_key_strategy: 'full_hierarchy' | 'top_level' | 'leaf';
  sensor_freshness_seconds: number;
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

export interface PowerMartingaleTracker extends MartingaleTrackerBase {
  betting_function: 'power';
  epsilon: number;
}

export interface SimpleMixtureMartingaleTracker extends MartingaleTrackerBase {
  betting_function: 'simple_mixture';
  epsilons?: number[] | null;
  n_grid: number;
  min_epsilon: number;
}

export interface SimpleJumperMartingaleTracker extends MartingaleTrackerBase {
  betting_function: 'simple_jumper';
  jump: number;
}

export type MartingaleTrackerConfig =
  | PowerMartingaleTracker
  | SimpleMixtureMartingaleTracker
  | SimpleJumperMartingaleTracker;

export interface StaticMartingaleConfig {
  trackers: MartingaleTrackerConfig[];
  automatic_threshold_calibration: {
    false_alarm_probability: number;
    horizon: number;
    simulation_count: number;
  };
}

export interface StaticBaselineRequestConfig {
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

export interface AdaptiveStreamRequestConfig {
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

export interface MonitoringEvidence {
  service_id: string;
  timestamp: string;
  sequence_number: number;
  charger_id: string;
  sensor_set: string[];
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

export interface MartingaleStatisticEvidence {
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

// Docker container status mapping
export interface StatusDisplay {
  label: string;
  className: string;
}

export interface ServiceDeleteActionDisplay {
  confirmation: string;
  success: string;
  ariaLabel: string;
}

export function getServiceDeleteActionDisplay(
  service: ActiveService
): ServiceDeleteActionDisplay {
  const dockerStatus = service.docker_status?.toLowerCase();
  const terminalStatuses = [
    'complete',
    'completed',
    'dead',
    'error',
    'exited',
    'failed',
    'not_found',
    'removed',
    'stopped',
  ];
  const isRunning = service.status && !terminalStatuses.includes(dockerStatus || '');
  const action = isRunning ? 'Stop and delete service' : 'Delete service record';

  return {
    confirmation: `${action} "${service.container_name}"?`,
    success: `Service "${service.container_name}" deleted`,
    ariaLabel: action.toLowerCase(),
  };
}

export function getOperationalStageDisplay(
  status: OperationalStatus
): StatusDisplay {
  switch (status.stage) {
    case 'starting':
      return {
        label: 'Starting',
        className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/35 dark:text-yellow-200',
      };
    case 'waiting_for_data':
      return {
        label: 'Waiting for data',
        className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/35 dark:text-yellow-200',
      };
    case 'collecting_training':
      return {
        label: 'Collecting training data',
        className: 'bg-sky-100 text-sky-800 dark:bg-sky-900/35 dark:text-sky-200',
      };
    case 'collecting_calibration':
      return {
        label: 'Calibrating',
        className: 'bg-blue-100 text-blue-800 dark:bg-blue-900/35 dark:text-blue-200',
      };
    case 'training':
      return {
        label: 'Training',
        className: 'bg-blue-100 text-blue-800 dark:bg-blue-900/35 dark:text-blue-200',
      };
    case 'operational':
      return {
        label: 'Operational',
        className: 'bg-green-100 text-green-800 dark:bg-green-900/35 dark:text-green-200',
      };
    case 'degraded':
      return {
        label: 'Degraded',
        className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/35 dark:text-yellow-200',
      };
    case 'failed':
      return {
        label: 'Failed',
        className: 'bg-red-100 text-red-800 dark:bg-red-900/35 dark:text-red-200',
      };
    case 'stopped':
      return {
        label: 'Stopped',
        className: 'bg-gray-100 text-gray-800 dark:bg-white/10 dark:text-gray-200',
      };
  }
}

/**
 * Get display properties for Docker status
 */
export function getStatusDisplay(
  dockerStatus: string | undefined,
  isActive: boolean
): StatusDisplay {
  const status = dockerStatus?.toLowerCase();
  switch (status) {
    case 'running':
      return {
        label: 'Running',
        className: 'bg-green-100 text-green-800 dark:bg-green-900/35 dark:text-green-200',
      };
    case 'complete':
    case 'completed':
      return {
        label: 'Completed',
        className: 'bg-blue-100 text-blue-800 dark:bg-blue-900/35 dark:text-blue-200',
      };
    case 'failed':
    case 'error':
    case 'dead':
      return {
        label: 'Failed',
        className: 'bg-red-100 text-red-800 dark:bg-red-900/35 dark:text-red-200',
      };
    // Docker reports "exited" for both successful exit code 0 and failures.
    // Keep this neutral until the API exposes exit code / termination reason.
    case 'exited':
      return {
        label: 'Exited',
        className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/35 dark:text-yellow-200',
      };
    case 'restarting':
      return {
        label: 'Restarting',
        className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/35 dark:text-yellow-200',
      };
    case 'removed':
    case 'stopped':
      return {
        label: 'Stopped',
        className: 'bg-gray-100 text-gray-800 dark:bg-white/10 dark:text-gray-200',
      };
    case 'not_found':
      return {
        label: 'Not Found',
        className: 'bg-gray-100 text-gray-800 dark:bg-white/10 dark:text-gray-200',
      };
    case 'pending':
    case 'assigned':
    case 'preparing':
    case 'starting':
      return {
        label: 'Starting',
        className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/35 dark:text-yellow-200',
      };
    default:
      if (!dockerStatus && !isActive) {
        return {
          label: 'Inactive',
          className: 'bg-gray-100 text-gray-800 dark:bg-white/10 dark:text-gray-200',
        };
      }
      return {
        label: dockerStatus || 'Active',
        className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/35 dark:text-yellow-200',
      };
  }
}
