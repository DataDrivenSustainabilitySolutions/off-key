/**
 * Types for monitoring and anomaly detection
 *
 * Replaces Record<string, any> usage in Monitoring.tsx
 */

// Parameter schema from model/preprocessor registry
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
export interface ActiveService {
  id: string;
  container_id: string;
  container_name: string;
  mqtt_topics: string[];
  status: boolean;
  docker_status?: string;
  created_at?: string;
}

// Preprocessing step configuration
export interface PreprocessingStepConfig {
  id?: string;
  type: string;
  params: Record<string, string | number | boolean>;
}

// Anomaly detection request payload
export interface AnomalyDetectionRequest {
  container_name: string;
  service_type: 'radar';
  mqtt_topics: string[];
  model_type: string;
  model_params: Record<string, string | number | boolean>;
  preprocessing_steps: PreprocessingStepConfig[];
}

// Model parameters (cleaned for API submission)
export type ModelParams = Record<string, string | number | boolean>;

// Docker container status mapping
export interface StatusDisplay {
  label: string;
  className: string;
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
        className: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
      };
    case 'complete':
    case 'completed':
      return {
        label: 'Completed',
        className: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
      };
    case 'failed':
    case 'error':
      return {
        label: 'Failed',
        className: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
      };
    case 'not_found':
      return {
        label: 'Not Found',
        className: 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200',
      };
    case 'pending':
    case 'assigned':
    case 'preparing':
    case 'starting':
      return {
        label: 'Starting',
        className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
      };
    default:
      if (!dockerStatus && !isActive) {
        return {
          label: 'Inactive',
          className: 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200',
        };
      }
      return {
        label: dockerStatus || 'Active',
        className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
      };
  }
}
