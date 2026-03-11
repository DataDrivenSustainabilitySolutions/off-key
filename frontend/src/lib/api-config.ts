/**
 * Centralized API configuration
 * Manages base URLs, endpoints, and API-related constants
 */

// Environment-based API configuration
const getApiBaseUrl = (): string => {
  // Use proxy in development, direct URL in production/Docker
  const isDevelopment = import.meta.env.DEV;

  if (isDevelopment) {
    // Use Vite proxy configuration
    return '/api';
  }

  // Production configuration - use environment variable or fallback
  return import.meta.env.VITE_API_URL || 'http://localhost:8000';
};

export const API_CONFIG = {
  BASE_URL: getApiBaseUrl(),
  TIMEOUT: 10000, // 10 seconds

  // API Endpoints
  ENDPOINTS: {
    // Authentication
    AUTH: {
      LOGIN: '/v1/auth/login',
      REGISTER: '/v1/auth/register',
      VERIFY_EMAIL: '/v1/auth/verify-email',
      FORGOT_PASSWORD: '/v1/auth/forgot-password',
      RESET_PASSWORD: '/v1/auth/reset-password',
    },

    // Chargers
    CHARGERS: {
      AVAILABLE: '/v1/chargers/available',
      SYNC: '/v1/chargers/sync',
      BY_ID: (chargerId: string) => `/v1/chargers/${chargerId}`,
    },

    // Telemetry
    TELEMETRY: {
      SYNC: (limit?: number) => `/v1/telemetry/sync${limit ? `?limit=${limit}` : ''}`,
      TYPES: (chargerId: string) => `/v1/telemetry/${chargerId}/type`,
      DATA: (chargerId: string, telemetryType: string, limit?: number) => {
        const params = new URLSearchParams({ type: telemetryType });
        if (limit) params.append('limit', limit.toString());
        return `/v1/telemetry/${chargerId}/data?${params.toString()}`;
      },
    },

    // Favorites
    FAVORITES: {
      GET: (userId: number) => `/v1/favorites?user_id=${userId}`,
      ADD: '/v1/favorites',
      REMOVE: '/v1/favorites',
    },

    // Anomalies
    ANOMALIES: {
      BASE: '/v1/anomalies',
      BY_CHARGER: (chargerId: string) =>
        `/v1/anomalies?charger_id=${chargerId}`,
      BY_CHARGER_AND_TYPE: (chargerId: string, telemetryType: string) =>
        `/v1/anomalies?charger_id=${chargerId}&telemetry_type=${telemetryType}`,
      CREATE: '/v1/anomalies',
      DELETE: (anomalyId: string) => `/v1/anomalies/${encodeURIComponent(anomalyId)}`,
    },

    // Monitoring Services
    MONITORING: {
      START: '/v1/monitors/start',
      STOP: '/v1/monitors/stop',
      LIST: '/v1/monitors/all',
      DETAILS: '/v1/monitors',
      MODELS: '/v1/monitors/models',
      PREPROCESSORS: '/v1/monitors/preprocessors',
    },

    // Monitoring & Anomaly Detection
    ANOMALY_DETECTION: {
      DETECT: '/v1/anomaly-detection/detect',
    },
  },
} as const;

/**
 * Constructs full API URL
 */
export const getApiUrl = (endpoint: string): string => {
  return `${API_CONFIG.BASE_URL}${endpoint}`;
};

/**
 * Request configuration defaults
 */
export const DEFAULT_REQUEST_CONFIG = {
  timeout: API_CONFIG.TIMEOUT,
  headers: {
    'Content-Type': 'application/json',
  },
};
