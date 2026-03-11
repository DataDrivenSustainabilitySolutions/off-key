/**
 * Unified Data Context
 *
 * Consolidates functionality from:
 * - FetchContext.tsx
 * - ChargerContext.tsx
 * - TelemetryContext.tsx
 *
 * Provides centralized data fetching and state management
 * for chargers, telemetry, and anomalies.
 */

import React, {
  createContext,
  useState,
  useCallback,
  useContext,
  ReactNode,
} from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import {
  Charger,
  TelemetryDataPoint,
  TelemetryData,
  CombinedChargerData,
  MonitoringData,
  TelemetryTypeData,
  Anomaly,
  getTelemetryCategory,
} from "@/types/charger";

// Re-export types for backward compatibility
export type {
  Charger,
  TelemetryDataPoint,
  TelemetryData,
  CombinedChargerData,
  MonitoringData,
  TelemetryTypeData,
  Anomaly,
};

// Context interface
export interface DataContextType {
  // Charger functions
  getAllChargers: () => Promise<Charger[]>;
  getCombinedChargerData: (chargers: Charger[]) => Promise<CombinedChargerData[]>;

  // Telemetry functions
  getTelemetryTypes: (chargerId: string) => Promise<string[]>;
  getTelemetryData: (
    chargerId: string,
    telemetryKey: string,
    limit?: number
  ) => Promise<TelemetryDataPoint[]>;
  loadAllTelemetryTypes: (chargerId: string) => Promise<void>;
  loadCpuUsage: (chargerId: string) => Promise<void>;
  loadCpuThermal: (chargerId: string) => Promise<void>;
  loadMonitoring: (chargerId: string) => Promise<void>;

  // Favorites functions
  getFavorites: (userId: number) => Promise<string[]>;
  toggleFavorite: (
    chargerId: string,
    userId: number,
    isCurrentlyFavorite: boolean
  ) => Promise<void>;

  // Anomaly functions
  getAnomalies: (chargerId: string) => Promise<Anomaly[]>;
  loadAnomalies: (chargerId: string) => Promise<void>;
  addAnomaly: (
    chargerId: string,
    timestamp: Date,
    telemetry_type: string,
    anomaly_type: string,
    anomaly_value: number
  ) => Promise<void>;
  deleteAnomaly: (anomalyId: string) => Promise<void>;

  // Sync functions
  syncChargers: () => Promise<void>;
  syncTelemetry: (limit?: number) => Promise<void>;

  // State maps
  chargers: Charger[];
  cpuUsageMap: Record<string, TelemetryDataPoint[]>;
  cpuThermalMap: Record<string, TelemetryDataPoint[]>;
  monitoringMap: Record<string, MonitoringData[]>;
  anomaliesMap: Record<string, Anomaly[]>;
  allTelemetryMap: Record<string, TelemetryTypeData[]>;
  telemetryTypes: Record<string, string[]>;

  // Status
  loading: boolean;
  error: string | null;

  // Clear functions
  clearData: (chargerId?: string) => void;
}

const DataContext = createContext<DataContextType | undefined>(undefined);

export const DataProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  // Charger state
  const [chargers, setChargers] = useState<Charger[]>([]);

  // Telemetry state
  const [cpuUsageMap, setCpuUsageMap] = useState<
    Record<string, TelemetryDataPoint[]>
  >({});
  const [cpuThermalMap, setCpuThermalMap] = useState<
    Record<string, TelemetryDataPoint[]>
  >({});
  const [monitoringMap, setMonitoringMap] = useState<
    Record<string, MonitoringData[]>
  >({});
  const [allTelemetryMap, setAllTelemetryMap] = useState<
    Record<string, TelemetryTypeData[]>
  >({});
  const [telemetryTypes, setTelemetryTypes] = useState<
    Record<string, string[]>
  >({});

  // Anomaly state
  const [anomaliesMap, setAnomaliesMap] = useState<Record<string, Anomaly[]>>(
    {}
  );

  // Loading state
  const [loadingCount, setLoadingCount] = useState(0);
  const loading = loadingCount > 0;
  const [error, setError] = useState<string | null>(null);

  const beginLoading = useCallback(() => {
    setLoadingCount((count) => count + 1);
  }, []);

  const endLoading = useCallback(() => {
    setLoadingCount((count) => (count > 0 ? count - 1 : 0));
  }, []);

  // ============================================
  // Charger Functions
  // ============================================

  const getAllChargers = useCallback(async (): Promise<Charger[]> => {
    const response = await apiUtils.get<Charger[]>(
      API_CONFIG.ENDPOINTS.CHARGERS.AVAILABLE
    );
    const normalized = response.map((charger) => ({
      ...charger,
      // Prefer live MQTT timestamp for "last seen" freshness.
      last_seen: charger.mqtt_last_message ?? charger.last_seen ?? "",
    }));
    setChargers(normalized);
    return normalized;
  }, []);

  const getCombinedChargerData = useCallback(
    async (chargerList: Charger[]): Promise<CombinedChargerData[]> => {
      beginLoading();
      setError(null);

      try {
        const combinedData = await Promise.all(
          chargerList.map(async (charger) => {
            try {
              const [value1Res, value2Res] = await Promise.all([
                apiUtils.get<TelemetryData[]>(
                  API_CONFIG.ENDPOINTS.TELEMETRY.DATA(
                    charger.charger_id,
                    "controllerCpuUsage"
                  )
                ),
                apiUtils.get<TelemetryData[]>(
                  API_CONFIG.ENDPOINTS.TELEMETRY.DATA(
                    charger.charger_id,
                    "controllertemperaturecpu-thermal"
                  )
                ),
              ]);

              return {
                charger_id: charger.charger_id,
                charger_name: charger.charger_name,
                online: charger.online,
                state: charger.state,
                last_seen: charger.last_seen,
                value1: value1Res[0]?.value ?? null,
                value2: value2Res[0]?.value ?? null,
              };
            } catch {
              return {
                charger_id: charger.charger_id,
                charger_name: charger.charger_name,
                online: charger.online,
                state: charger.state,
                last_seen: charger.last_seen,
                value1: null,
                value2: null,
              };
            }
          })
        );

        return combinedData;
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to get combined charger data";
        setError(errorMessage);
        throw err;
      } finally {
        endLoading();
      }
    },
    [beginLoading, endLoading]
  );

  // ============================================
  // Telemetry Functions
  // ============================================

  const getTelemetryTypes = useCallback(
    async (chargerId: string): Promise<string[]> => {
      return await apiUtils.get<string[]>(
        API_CONFIG.ENDPOINTS.TELEMETRY.TYPES(chargerId)
      );
    },
    []
  );

  const getTelemetryData = useCallback(
    async (
      chargerId: string,
      telemetryKey: string,
      limit = 1000
    ): Promise<TelemetryDataPoint[]> => {
      return await apiUtils.get<TelemetryDataPoint[]>(
        API_CONFIG.ENDPOINTS.TELEMETRY.DATA(chargerId, telemetryKey, limit)
      );
    },
    []
  );

  const loadCpuUsage = useCallback(
    async (chargerId: string) => {
      if (!chargerId) return;

      try {
        beginLoading();
        setError(null);

        const types = await getTelemetryTypes(chargerId);
        const cpuUsageKey = types.find((t) =>
          t.toLowerCase().includes("controllercpuusage")
        );

        if (!cpuUsageKey) {
          throw new Error(`CPU Usage key not found for charger ${chargerId}`);
        }

        const data = await getTelemetryData(chargerId, cpuUsageKey);

        setCpuUsageMap((prev) => ({
          ...prev,
          [chargerId]: data,
        }));
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to load CPU usage data";
        setError(errorMessage);
      } finally {
        endLoading();
      }
    },
    [beginLoading, endLoading, getTelemetryTypes, getTelemetryData]
  );

  const loadCpuThermal = useCallback(
    async (chargerId: string) => {
      if (!chargerId) return;

      try {
        beginLoading();
        setError(null);

        const types = await getTelemetryTypes(chargerId);
        const cpuThermalKey = types.find((t) =>
          t.toLowerCase().includes("controllertemperaturecpu-thermal")
        );

        if (!cpuThermalKey) {
          throw new Error(`CPU Thermal key not found for charger ${chargerId}`);
        }

        const data = await getTelemetryData(chargerId, cpuThermalKey);

        setCpuThermalMap((prev) => ({
          ...prev,
          [chargerId]: data,
        }));
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to load CPU thermal data";
        setError(errorMessage);
      } finally {
        endLoading();
      }
    },
    [beginLoading, endLoading, getTelemetryTypes, getTelemetryData]
  );

  const loadMonitoring = useCallback(
    async (chargerId: string) => {
      if (!chargerId) return;

      try {
        beginLoading();
        setError(null);

        const types = await getTelemetryTypes(chargerId);
        const keys = types.filter(
          (t) =>
            t.toLowerCase().startsWith("system") ||
            t.toLowerCase().startsWith("controllerstate")
        );

        if (keys.length === 0) {
          throw new Error(`No monitoring keys found for charger ${chargerId}`);
        }

        const entries = await Promise.all(
          keys.map(async (key) => {
            const rawData = await getTelemetryData(chargerId, key);
            const data: MonitoringData[] = rawData.map((d) => ({
              type: key,
              value: d.value,
            }));
            return [key, data] as const;
          })
        );

        setMonitoringMap((prev) => ({
          ...prev,
          [chargerId]: entries.flatMap(([, data]) => data),
        }));
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to load monitoring data";
        setError(errorMessage);
      } finally {
        endLoading();
      }
    },
    [beginLoading, endLoading, getTelemetryTypes, getTelemetryData]
  );

  const loadAllTelemetryTypes = useCallback(
    async (chargerId: string) => {
      if (!chargerId) return;

      try {
        beginLoading();
        setError(null);

        const types = await getTelemetryTypes(chargerId);
        setTelemetryTypes((prev) => ({
          ...prev,
          [chargerId]: types,
        }));

        const telemetryData = await Promise.all(
          types.map(async (type) => {
            try {
              const data = await getTelemetryData(chargerId, type);
              const category = getTelemetryCategory(type);
              return {
                type,
                category,
                data,
              } as TelemetryTypeData;
            } catch {
              return null;
            }
          })
        );

        const successfulData = telemetryData.filter(
          (item): item is TelemetryTypeData => item !== null
        );
        setAllTelemetryMap((prev) => ({
          ...prev,
          [chargerId]: successfulData,
        }));
      } catch (err) {
        const errorMessage =
          err instanceof Error
            ? err.message
            : "Failed to load all telemetry types";
        setError(errorMessage);
      } finally {
        endLoading();
      }
    },
    [beginLoading, endLoading, getTelemetryTypes, getTelemetryData]
  );

  // ============================================
  // Favorites Functions
  // ============================================

  const getFavorites = useCallback(
    async (userId: number): Promise<string[]> => {
      return await apiUtils.get<string[]>(
        API_CONFIG.ENDPOINTS.FAVORITES.GET(userId)
      );
    },
    []
  );

  const toggleFavorite = useCallback(
    async (
      chargerId: string,
      userId: number,
      isCurrentlyFavorite: boolean
    ): Promise<void> => {
      if (isCurrentlyFavorite) {
        await apiUtils.delete(API_CONFIG.ENDPOINTS.FAVORITES.REMOVE, {
          charger_id: chargerId,
          user_id: userId,
        });
      } else {
        await apiUtils.post(API_CONFIG.ENDPOINTS.FAVORITES.ADD, {
          charger_id: chargerId,
          user_id: userId,
        });
      }
    },
    []
  );

  // ============================================
  // Anomaly Functions
  // ============================================

  const getAnomalies = useCallback(
    async (chargerId: string): Promise<Anomaly[]> => {
      return await apiUtils.get<Anomaly[]>(
        API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(chargerId)
      );
    },
    []
  );

  const loadAnomalies = useCallback(
    async (chargerId: string) => {
      try {
        const anomalies = await getAnomalies(chargerId);
        setAnomaliesMap((prev) => ({
          ...prev,
          [chargerId]: anomalies,
        }));
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to load anomalies";
        setError(errorMessage);
      }
    },
    [getAnomalies]
  );

  const addAnomaly = useCallback(
    async (
      chargerId: string,
      timestamp: Date,
      telemetry_type: string,
      anomaly_type: string,
      anomaly_value: number
    ): Promise<void> => {
      await apiUtils.post(API_CONFIG.ENDPOINTS.ANOMALIES.CREATE, {
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
    async (anomalyId: string): Promise<void> => {
      if (!anomalyId) {
        throw new Error("Anomaly ID is required");
      }
      await apiUtils.delete(API_CONFIG.ENDPOINTS.ANOMALIES.DELETE(anomalyId));
    },
    []
  );

  // ============================================
  // Sync Functions
  // ============================================

  const syncChargers = useCallback(async (): Promise<void> => {
    try {
      await apiUtils.post(API_CONFIG.ENDPOINTS.CHARGERS.SYNC, null);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to sync chargers";
      setError(errorMessage);
    }
  }, []);

  const syncTelemetry = useCallback(
    async (limit = 10000): Promise<void> => {
      try {
        await apiUtils.post(API_CONFIG.ENDPOINTS.TELEMETRY.SYNC(limit), null);
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to sync telemetry";
        setError(errorMessage);
      }
    },
    []
  );

  // ============================================
  // Clear Functions
  // ============================================

  const clearData = useCallback((chargerId?: string) => {
    if (chargerId) {
      setCpuUsageMap((prev) => {
        const { [chargerId]: _, ...rest } = prev;
        return rest;
      });
      setCpuThermalMap((prev) => {
        const { [chargerId]: _, ...rest } = prev;
        return rest;
      });
      setMonitoringMap((prev) => {
        const { [chargerId]: _, ...rest } = prev;
        return rest;
      });
      setAnomaliesMap((prev) => {
        const { [chargerId]: _, ...rest } = prev;
        return rest;
      });
      setAllTelemetryMap((prev) => {
        const { [chargerId]: _, ...rest } = prev;
        return rest;
      });
      setTelemetryTypes((prev) => {
        const { [chargerId]: _, ...rest } = prev;
        return rest;
      });
    } else {
      setCpuUsageMap({});
      setCpuThermalMap({});
      setMonitoringMap({});
      setAnomaliesMap({});
      setAllTelemetryMap({});
      setTelemetryTypes({});
      setChargers([]);
    }
  }, []);

  return (
    <DataContext.Provider
      value={{
        // Charger functions
        getAllChargers,
        getCombinedChargerData,

        // Telemetry functions
        getTelemetryTypes,
        getTelemetryData,
        loadAllTelemetryTypes,
        loadCpuUsage,
        loadCpuThermal,
        loadMonitoring,

        // Favorites functions
        getFavorites,
        toggleFavorite,

        // Anomaly functions
        getAnomalies,
        loadAnomalies,
        addAnomaly,
        deleteAnomaly,

        // Sync functions
        syncChargers,
        syncTelemetry,

        // State maps
        chargers,
        cpuUsageMap,
        cpuThermalMap,
        monitoringMap,
        anomaliesMap,
        allTelemetryMap,
        telemetryTypes,

        // Status
        loading,
        error,

        // Clear functions
        clearData,
      }}
    >
      {children}
    </DataContext.Provider>
  );
};

/**
 * Hook to use the unified data context
 */
export const useData = (): DataContextType => {
  const context = useContext(DataContext);
  if (!context) {
    throw new Error("useData must be used within a DataProvider");
  }
  return context;
};

// Backward compatibility aliases
export {
  DataProvider as UnifiedDataProvider,
  useData as useUnifiedData,
};
