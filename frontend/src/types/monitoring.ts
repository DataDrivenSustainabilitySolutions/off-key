/**
 * Types for monitoring and anomaly detection
 *
 * Replaces Record<string, any> usage in Monitoring.tsx
 */

// Parameter schema from model/preprocessor registry
export type MonitoringStrategy = 'static_baseline' | 'adaptive_stream';

export interface ParameterSchema {
  type: 'string' | 'number' | 'integer' | 'boolean' | 'array' | 'object';
  description?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  enum?: (string | number)[];
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
  strategy?: MonitoringStrategy;
  default_parameters?: Record<string, string | number | boolean | null>;
}

// Preprocessor definition from registry API
export interface PreprocessorDefinition {
  parameters: {
    properties: Record<string, ParameterSchema>;
    required?: string[];
  };
  description?: string;
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
  monitoring_strategy?: MonitoringStrategy;
  model_type?: string;
  created_at?: string;
}

// Preprocessing step configuration
export interface PreprocessingStepConfig {
  id?: string;
  type: string;
  params: Record<string, string | number | boolean>;
}

export interface MonitoringPerformanceConfig {
  heuristic_enabled?: boolean;
  heuristic_window_size?: number;
  heuristic_min_samples?: number;
  heuristic_tail_alpha?: number;
  alignment_mode: 'strict_barrier';
  sensor_key_strategy: 'full_hierarchy' | 'top_level' | 'leaf';
  sensor_freshness_seconds: number;
}

export interface StaticMartingaleConfig {
  method: 'power';
  epsilon: number;
  alpha: number;
}

export interface StaticBaselineRequestConfig {
  model_type: string;
  model_params: Record<string, string | number | boolean>;
  training_window_size: number;
  calibration_window_size: number;
  conformal_strategy: 'split';
  martingale_config: StaticMartingaleConfig;
}

export interface AdaptiveStreamRequestConfig {
  model_type: string;
  model_params: Record<string, string | number | boolean>;
  preprocessing_steps: PreprocessingStepConfig[];
  performance_config: MonitoringPerformanceConfig;
}

// Anomaly detection request payload
export interface AnomalyDetectionRequest {
  container_name: string;
  service_type: 'radar';
  mqtt_topics: string[];
  strategy: MonitoringStrategy;
  model_type: string;
  model_params: Record<string, string | number | boolean>;
  preprocessing_steps: PreprocessingStepConfig[];
  performance_config: MonitoringPerformanceConfig;
  static_baseline_config?: StaticBaselineRequestConfig;
  adaptive_stream_config?: AdaptiveStreamRequestConfig;
}

// Model parameters (cleaned for API submission)
export type ModelParams = Record<string, string | number | boolean>;

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
