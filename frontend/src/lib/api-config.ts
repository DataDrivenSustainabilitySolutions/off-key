/**
 * Centralized API configuration
 * Manages base URLs, endpoints, and API-related constants
 */

import { EVIDENCE_PAGE_SIZE } from "./forward-pages";
import { isoTimestamp } from "./timestamps";

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

    // Recorded values of catalogue readings
    READINGS: {
      MEASUREMENTS: (
        readingId: string,
        limit?: number,
        cursor?: { created: string; timestamp: string },
      ) => {
        const params = new URLSearchParams();
        if (limit) params.append('limit', limit.toString());
        if (cursor) {
          params.append('after_created', cursor.created);
          params.append('after_event_timestamp', cursor.timestamp);
        }
        const query = params.toString();
        return `/v1/readings/${encodeURIComponent(readingId)}/measurements${query ? `?${query}` : ''}`;
      },
      BUCKETS: (
        readingId: string,
        { startMs, endMs, buckets }: { startMs?: number; endMs?: number; buckets?: number },
      ) => {
        const params = new URLSearchParams();
        if (startMs !== undefined) params.append('start', isoTimestamp(startMs));
        if (endMs !== undefined) params.append('end', isoTimestamp(endMs));
        if (buckets) params.append('buckets', buckets.toString());
        const query = params.toString();
        return `/v1/readings/${encodeURIComponent(readingId)}/measurements/buckets${query ? `?${query}` : ''}`;
      },
    },

    // Alarms of catalogue devices and readings
    ALARMS: {
      QUERY: '/v1/alarms/query',
      ITEM: (alarmId: string) => `/v1/alarms/${encodeURIComponent(alarmId)}`,
      /** The newest alarms of a device, or of the named readings. */
      LIST: (scope: { deviceId: string } | { readingIds: readonly string[] }) => {
        const params = new URLSearchParams();
        if ('deviceId' in scope) params.append('device_id', scope.deviceId);
        else scope.readingIds.forEach((id) => params.append('reading_id', id));
        return `/v1/alarms?${params}`;
      },
      DELETE: (alarmId: string) => `/v1/alarms/${encodeURIComponent(alarmId)}`,
    },

    // The signed-in member's favourites
    FAVORITES: '/v1/favorites',

    // Monitoring Services
    MONITORING: {
      LIST: '/v1/monitors',
      OVERVIEW: '/v1/monitors/overview',
      ITEM: (monitorId: string) => `/v1/monitors/${encodeURIComponent(monitorId)}`,
      DETECTORS: '/v1/detectors',
      /** Evidence of every reading of a device, or of the named readings. */
      CHART_EVIDENCE: (
        scope: { deviceId: string } | { readingIds: readonly string[] },
        cursor?: {
          created: string;
          timestamp: string;
          monitor_id: string;
          sequence_number: number;
        },
        monitorId?: string,
      ) => {
        const params = new URLSearchParams();
        if ('deviceId' in scope) params.set('device_id', scope.deviceId);
        else scope.readingIds.forEach(readingId => params.append('reading_id', readingId));
        params.set('limit', EVIDENCE_PAGE_SIZE.toString());
        if (monitorId) params.set('monitor_id', monitorId);
        if (cursor) {
          params.set('after_created', cursor.created);
          params.set('after_timestamp', cursor.timestamp);
          params.set('after_monitor_id', cursor.monitor_id);
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
