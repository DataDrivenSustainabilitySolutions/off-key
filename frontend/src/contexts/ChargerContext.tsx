import React, { createContext, useState, useCallback, ReactNode, useContext } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";

export interface Charger {
  charger_name: string | null;
  last_seen: string;
  online: boolean;
  charger_id: string;
  state: string;
  created: string;
}

export interface TelemetryData {
  charger_id: string;
  timestamp: string;
  value: number;
}

export interface CombinedData {
  charger_id: string;
  charger_name: string | null;
  online: boolean;
  state: string;
  last_seen: string;
  value1?: number | null;
  value2?: number | null;
}

export interface Monitoring {
  type: string;
  value: number;
}

export interface ChargerContextType {
  // Core charger functions
  getAllChargers: () => Promise<Charger[]>;
  getCombinedChargerData: (chargers: Charger[]) => Promise<CombinedData[]>;
  
  // Sync functions
  syncChargers: () => Promise<void>;
  syncTelemetry: () => Promise<void>;
  syncTelemetryShort: () => Promise<void>;
  
  // Monitoring functions
  loadMonitoring: (chargerId: string) => Promise<void>;
  
  // State management
  monitoringMap: Record<string, Monitoring[]>;
  chargers: Charger[];
  
  // Loading and error states
  loading: boolean;
  error: string | null;
  
  // Clear functions
  clearMonitoringData: (chargerId?: string) => void;
  clearChargers: () => void;
}

const ChargerContext = createContext<ChargerContextType | undefined>(undefined);

export const ChargerProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [monitoringMap, setMonitoringMap] = useState<Record<string, Monitoring[]>>({});
  const [chargers, setChargers] = useState<Charger[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getAllChargers = useCallback(async (): Promise<Charger[]> => {
    const endpoint = API_CONFIG.ENDPOINTS.CHARGERS.AVAILABLE;
    const chargersData = await apiUtils.get<Charger[]>(endpoint);
    setChargers(chargersData);
    return chargersData;
  }, []);

  const getCombinedChargerData = useCallback(
    async (chargers: Charger[]): Promise<CombinedData[]> => {
      try {
        setLoading(true);
        setError(null);
        
        const combinedData = await Promise.all(
          chargers.map(async (charger) => {
            try {
              const [value1Res, value2Res] = await Promise.all([
                apiUtils.get<TelemetryData[]>(
                  API_CONFIG.ENDPOINTS.TELEMETRY.DATA(charger.charger_id, "controllerCpuUsage")
                ),
                apiUtils.get<TelemetryData[]>(
                  API_CONFIG.ENDPOINTS.TELEMETRY.DATA(charger.charger_id, "controllertemperaturecpu-thermal")
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
            } catch (error) {
              console.warn(
                `Error getting telemetry values for charger ${charger.charger_id}`,
                error
              );
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
        const errorMessage = err instanceof Error ? err.message : 'Failed to get combined charger data';
        setError(errorMessage);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const syncChargers = useCallback(async (): Promise<void> => {
    try {
      const endpoint = API_CONFIG.ENDPOINTS.CHARGERS.SYNC;
      await apiUtils.post(endpoint, null);
    } catch (err) {
      console.warn("syncChargers failed:", err);
      throw err;
    }
  }, []);

  const syncTelemetry = useCallback(async (): Promise<void> => {
    try {
      const endpoint = API_CONFIG.ENDPOINTS.TELEMETRY.SYNC(10000);
      await apiUtils.post(endpoint, null);
    } catch (err) {
      console.warn("syncTelemetry failed:", err);
      throw err;
    }
  }, []);

  const syncTelemetryShort = useCallback(async (): Promise<void> => {
    try {
      const endpoint = API_CONFIG.ENDPOINTS.TELEMETRY.SYNC(100);
      await apiUtils.post(endpoint, null);
    } catch (err) {
      console.warn("syncTelemetryShort failed:", err);
      throw err;
    }
  }, []);

  const loadMonitoring = useCallback(async (chargerId: string) => {
    if (!chargerId) return;
    
    try {
      setLoading(true);
      setError(null);
      
      const typesEndpoint = API_CONFIG.ENDPOINTS.TELEMETRY.TYPES(chargerId);
      const types = await apiUtils.get<string[]>(typesEndpoint);
      
      const keys = types.filter(
        (t) =>
          t.toLowerCase().startsWith("system") ||
          t.toLowerCase().startsWith("controllerstate")
      );
      
      if (keys.length === 0) {
        throw new Error(
          `No monitoring keys found for charger ${chargerId}`
        );
      }

      const entries = await Promise.all(
        keys.map(async (key) => {
          const dataEndpoint = API_CONFIG.ENDPOINTS.TELEMETRY.DATA(chargerId, key);
          const rawData = await apiUtils.get<{ timestamp: string; value: number }[]>(dataEndpoint);
          const data: Monitoring[] = rawData.map((d) => ({
            type: key,
            value: d.value,
          }));
          return [key, data] as const;
        })
      );

      setMonitoringMap((prev) => ({
        ...prev,
        ...Object.fromEntries(entries),
      }));
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load monitoring data';
      setError(errorMessage);
      console.error("Error loading monitoring data:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  const clearMonitoringData = useCallback((chargerId?: string) => {
    if (chargerId) {
      setMonitoringMap(prev => {
        const newMap = { ...prev };
        Object.keys(newMap).forEach(key => {
          if (newMap[key][0]?.type?.includes(chargerId)) {
            delete newMap[key];
          }
        });
        return newMap;
      });
    } else {
      setMonitoringMap({});
    }
  }, []);

  const clearChargers = useCallback(() => {
    setChargers([]);
  }, []);

  return (
    <ChargerContext.Provider
      value={{
        getAllChargers,
        getCombinedChargerData,
        syncChargers,
        syncTelemetry,
        syncTelemetryShort,
        loadMonitoring,
        monitoringMap,
        chargers,
        loading,
        error,
        clearMonitoringData,
        clearChargers,
      }}
    >
      {children}
    </ChargerContext.Provider>
  );
};

export const useCharger = (): ChargerContextType => {
  const context = useContext(ChargerContext);
  if (!context) {
    throw new Error("useCharger must be used within a ChargerProvider");
  }
  return context;
};