import React, { createContext, useState, useCallback, ReactNode, useContext } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { Anomaly } from "@/lib/anomaly-utils";

export interface AnomalyContextType {
  // Core anomaly functions
  getAnomalies: (chargerId: string) => Promise<Anomaly[]>;
  addAnomaly: (
    chargerId: string,
    timestamp: Date,
    telemetry_type: string,
    anomaly_type: string,
    anomaly_value: number
  ) => Promise<void>;
  deleteAnomaly: (
    chargerId: string,
    timestamp: Date,
    telemetry_type: string
  ) => Promise<void>;
  
  // Data loading functions
  loadAnomalies: (chargerId: string) => Promise<void>;
  
  // State management
  anomaliesMap: Record<string, Anomaly[]>;
  
  // Loading and error states
  loading: boolean;
  error: string | null;
  
  // Clear functions
  clearAnomalies: (chargerId?: string) => void;
  
  // Real-time updates
  refreshAnomalies: (chargerId: string) => Promise<void>;
}

const AnomalyContext = createContext<AnomalyContextType | undefined>(undefined);

export const AnomalyProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [anomaliesMap, setAnomaliesMap] = useState<Record<string, Anomaly[]>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getAnomalies = useCallback(
    async (chargerId: string): Promise<Anomaly[]> => {
      if (!chargerId) throw new Error('Charger ID is required');
      
      const endpoint = API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(chargerId);
      return await apiUtils.get<Anomaly[]>(endpoint);
    },
    []
  );

  const addAnomaly = useCallback(
    async (
      chargerId: string,
      timestamp: Date,
      telemetry_type: string,
      anomaly_type: string,
      anomaly_value: number
    ) => {
      if (!chargerId || !timestamp || !telemetry_type || !anomaly_type) {
        throw new Error('All anomaly fields are required');
      }
      
      const endpoint = API_CONFIG.ENDPOINTS.ANOMALIES.CREATE;
      await apiUtils.post(endpoint, {
        charger_id: chargerId,
        timestamp: timestamp,
        telemetry_type: telemetry_type,
        anomaly_type: anomaly_type,
        anomaly_value: anomaly_value,
      });
    },
    []
  );

  const deleteAnomaly = useCallback(
    async (chargerId: string, timestamp: Date, telemetry_type: string) => {
      if (!chargerId || !timestamp || !telemetry_type) {
        throw new Error('Charger ID, timestamp, and telemetry type are required');
      }
      
      const params = new URLSearchParams({
        charger_id: chargerId,
        timestamp: timestamp.toISOString(),
        telemetry_type: telemetry_type,
      });

      const endpoint = `${API_CONFIG.ENDPOINTS.ANOMALIES.DELETE}?${params.toString()}`;
      await apiUtils.delete(endpoint);
    },
    []
  );

  const loadAnomalies = useCallback(async (chargerId: string) => {
    if (!chargerId) return;
    
    try {
      setLoading(true);
      setError(null);
      
      const anomalies = await getAnomalies(chargerId);
      
      setAnomaliesMap((prev) => ({
        ...prev,
        [chargerId]: anomalies,
      }));
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load anomalies';
      setError(errorMessage);
      console.error("Error loading anomalies:", err);
    } finally {
      setLoading(false);
    }
  }, [getAnomalies]);

  const refreshAnomalies = useCallback(async (chargerId: string) => {
    await loadAnomalies(chargerId);
  }, [loadAnomalies]);

  const clearAnomalies = useCallback((chargerId?: string) => {
    if (chargerId) {
      setAnomaliesMap(prev => {
        const { [chargerId]: removed, ...rest } = prev;
        return rest;
      });
    } else {
      setAnomaliesMap({});
    }
  }, []);

  return (
    <AnomalyContext.Provider
      value={{
        getAnomalies,
        addAnomaly,
        deleteAnomaly,
        loadAnomalies,
        anomaliesMap,
        loading,
        error,
        clearAnomalies,
        refreshAnomalies,
      }}
    >
      {children}
    </AnomalyContext.Provider>
  );
};

export const useAnomaly = (): AnomalyContextType => {
  const context = useContext(AnomalyContext);
  if (!context) {
    throw new Error("useAnomaly must be used within an AnomalyProvider");
  }
  return context;
};