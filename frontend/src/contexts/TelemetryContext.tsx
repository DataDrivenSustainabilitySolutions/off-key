import React, { createContext, useState, useCallback, ReactNode, useContext } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";

export interface Cpu {
  timestamp: string;
  value: number;
}

export interface TelemetryData {
  charger_id: string;
  timestamp: string;
  value: number;
}

export interface TelemetryContextType {
  // Core telemetry functions
  getTelemetryTypes: (chargerId: string) => Promise<string[]>;
  getTelemetryData: (chargerId: string, telemetryKey: string) => Promise<Cpu[]>;
  
  // Data loading functions
  loadCpuUsage: (chargerId: string) => Promise<void>;
  loadCpuThermal: (chargerId: string) => Promise<void>;
  
  // State maps
  cpuUsageMap: Record<string, Cpu[]>;
  cpuThermalMap: Record<string, Cpu[]>;
  
  // Loading states
  loading: boolean;
  error: string | null;
  
  // Clear functions
  clearTelemetryData: (chargerId?: string) => void;
}

const TelemetryContext = createContext<TelemetryContextType | undefined>(undefined);

export const TelemetryProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [cpuUsageMap, setCpuUsageMap] = useState<Record<string, Cpu[]>>({});
  const [cpuThermalMap, setCpuThermalMap] = useState<Record<string, Cpu[]>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getTelemetryTypes = useCallback(
    async (chargerId: string): Promise<string[]> => {
      if (!chargerId) throw new Error('Charger ID is required');
      
      const endpoint = API_CONFIG.ENDPOINTS.TELEMETRY.TYPES(chargerId);
      return await apiUtils.get<string[]>(endpoint);
    },
    []
  );

  const getTelemetryData = useCallback(
    async (chargerId: string, telemetryKey: string): Promise<Cpu[]> => {
      if (!chargerId || !telemetryKey) {
        throw new Error('Charger ID and telemetry key are required');
      }
      
      const endpoint = API_CONFIG.ENDPOINTS.TELEMETRY.DATA(chargerId, telemetryKey, 1000);
      return await apiUtils.get<Cpu[]>(endpoint);
    },
    []
  );

  const loadCpuUsage = useCallback(
    async (chargerId: string) => {
      if (!chargerId) return;
      
      try {
        setLoading(true);
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
        const errorMessage = err instanceof Error ? err.message : 'Failed to load CPU usage data';
        setError(errorMessage);
        console.error("Error loading CPU Usage:", err);
      } finally {
        setLoading(false);
      }
    },
    [getTelemetryTypes, getTelemetryData]
  );

  const loadCpuThermal = useCallback(
    async (chargerId: string) => {
      if (!chargerId) return;
      
      try {
        setLoading(true);
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
        const errorMessage = err instanceof Error ? err.message : 'Failed to load CPU thermal data';
        setError(errorMessage);
        console.error("Error loading CPU Thermal:", err);
      } finally {
        setLoading(false);
      }
    },
    [getTelemetryTypes, getTelemetryData]
  );

  const clearTelemetryData = useCallback((chargerId?: string) => {
    if (chargerId) {
      setCpuUsageMap(prev => {
        const { [chargerId]: removed, ...rest } = prev;
        return rest;
      });
      setCpuThermalMap(prev => {
        const { [chargerId]: removed, ...rest } = prev;
        return rest;
      });
    } else {
      setCpuUsageMap({});
      setCpuThermalMap({});
    }
  }, []);

  return (
    <TelemetryContext.Provider
      value={{
        getTelemetryTypes,
        getTelemetryData,
        loadCpuUsage,
        loadCpuThermal,
        cpuUsageMap,
        cpuThermalMap,
        loading,
        error,
        clearTelemetryData,
      }}
    >
      {children}
    </TelemetryContext.Provider>
  );
};

export const useTelemetry = (): TelemetryContextType => {
  const context = useContext(TelemetryContext);
  if (!context) {
    throw new Error("useTelemetry must be used within a TelemetryProvider");
  }
  return context;
};