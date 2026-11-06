/**
 * Centralized API configuration
 * Manages base URLs, endpoints, and API-related constants
 */

import { EVIDENCE_PAGE_SIZE } from "./forward-pages";

export const API_CONFIG = {
  // Same-origin in every mode: Vite's dev proxy and the production nginx
  // both forward /api to the gateway.
  BASE_URL: '/api',
  TIMEOUT: 10000, // 10 seconds
  MONITORING_LIFECYCLE_TIMEOUT: 210000, // 210 seconds

  // API Endpoints
  ENDPOINTS: {
    // Authentication
    AUTH: {
      LOGIN: '/v1/auth/login',
      REFRESH: '/v1/auth/refresh',
      LOGOUT: '/v1/auth/logout',
      PASSWORD_RESET: '/v1/auth/password-reset',
      PASSWORD_RESET_CONFIRM: '/v1/auth/password-reset/confirm',
    },

    // Chargers
    CHARGERS: {
      AVAILABLE: '/v1/chargers/available',
    },

    // Telemetry
    TELEMETRY: {
      TYPES: (chargerId: string) => `/v1/telemetry/${chargerId}/type`,
      DATA: (
        chargerId: string,
        telemetryType: string,
        limit?: number,
        cursor?: { created: string; timestamp: string },
      ) => {
        const params = new URLSearchParams({ type: telemetryType });
        if (limit) params.append('limit', limit.toString());
        if (cursor) {
          params.append('after_created', cursor.created);
          params.append('after_event_timestamp', cursor.timestamp);
        }
        return `/v1/telemetry/${chargerId}/data?${params.toString()}`;
      },
      RANGE: (
        chargerId: string,
        telemetryType: string,
        { startMs, endMs, buckets }: { startMs?: number; endMs?: number; buckets?: number },
      ) => {
        const params = new URLSearchParams({ type: telemetryType });
        if (startMs !== undefined) params.append('start', new Date(startMs).toISOString());
        if (endMs !== undefined) params.append('end', new Date(endMs).toISOString());
        if (buckets) params.append('buckets', buckets.toString());
        return `/v1/telemetry/${encodeURIComponent(chargerId)}/range?${params.toString()}`;
      },
    },

    // Anomalies
    ANOMALIES: {
      QUERY: '/v1/anomalies/query',
      BY_CHARGER: (chargerId: string) =>
        `/v1/anomalies?charger_id=${chargerId}`,
      DELETE: (anomalyId: string) => `/v1/anomalies/${encodeURIComponent(anomalyId)}`,
    },

    // The signed-in member's favourites
    FAVORITES: '/v1/favorites',

    // Monitoring Services
    MONITORING: {
      LIST: '/v1/monitors',
      OVERVIEW: '/v1/monitors/overview',
      ITEM: (monitorId: string) => `/v1/monitors/${encodeURIComponent(monitorId)}`,
      DETECTORS: '/v1/detectors',
      CHART_EVIDENCE: (
        chargerId: string,
        cursor?: {
          created: string;
          timestamp: string;
          service_id: string;
          sequence_number: number;
        },
        serviceId?: string,
      ) => {
        const params = new URLSearchParams({
          charger_id: chargerId,
          limit: EVIDENCE_PAGE_SIZE.toString(),
        });
        if (serviceId) params.set('service_id', serviceId);
        if (cursor) {
          params.set('after_created', cursor.created);
          params.set('after_timestamp', cursor.timestamp);
          params.set('after_service_id', cursor.service_id);
          params.set('after_sequence_number', cursor.sequence_number.toString());
        }
        return `/v1/evidence/chart?${params.toString()}`;
      },
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
