/**
 * Custom hook for fetching and managing anomaly data
 */

import { useState, useEffect, useCallback } from 'react';
import { apiUtils } from '@/lib/api-client';
import { API_CONFIG } from '@/lib/api-config';
import { Anomaly } from '@/lib/anomaly-utils';
import { INTERVALS } from '@/lib/constants';

export interface UseAnomaliesResult {
  anomalies: Anomaly[];
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export interface UseAnomaliesOptions {
  chargerId: string;
  telemetryType?: string;
  autoRefresh?: boolean;
  refreshInterval?: number;
}

/**
 * Hook to fetch anomalies for a specific charger
 * Optionally filters by telemetry type and supports auto-refresh
 */
export const useAnomalies = ({
  chargerId,
  telemetryType,
  autoRefresh = false,
  refreshInterval = INTERVALS.REAL_TIME_UPDATE, // 1 minute default
}: UseAnomaliesOptions): UseAnomaliesResult => {
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAnomalies = useCallback(async () => {
    if (!chargerId) return;
    
    try {
      setError(null);
      
      // Choose appropriate endpoint based on whether telemetry type is specified
      const endpoint = telemetryType 
        ? API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER_AND_TYPE(chargerId, telemetryType)
        : API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(chargerId);
      
      const fetchedAnomalies = await apiUtils.get<Anomaly[]>(endpoint);
      setAnomalies(fetchedAnomalies);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch anomalies';
      setError(errorMessage);
      console.error('Error fetching anomalies:', err);
    } finally {
      setLoading(false);
    }
  }, [chargerId, telemetryType]);

  // Initial fetch
  useEffect(() => {
    setLoading(true);
    fetchAnomalies();
  }, [fetchAnomalies]);

  // Auto-refresh setup
  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      fetchAnomalies();
    }, refreshInterval);

    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, fetchAnomalies]);

  return {
    anomalies,
    loading,
    error,
    refetch: fetchAnomalies,
  };
};

/**
 * Simplified hook for getting anomalies without auto-refresh
 */
export const useAnomaliesOnce = (chargerId: string, telemetryType?: string) => {
  return useAnomalies({
    chargerId,
    telemetryType,
    autoRefresh: false,
  });
};