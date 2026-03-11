import React, { createContext, useState, useCallback, ReactNode } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";

// Interface CPU
export interface Cpu {
  timestamp: string;
  value: number;
}

export interface Monitoring {
  type: string;
  value: number;
}

export interface TelemetryTypeData {
  type: string;
  category: 'cpu' | 'system' | 'controller' | 'other';
  data: Cpu[];
}
// Interface Charger
export interface Charger {
  charger_name: string | null;
  last_seen: string;
  mqtt_last_message?: string | null;
  online: boolean;
  charger_id: string;
  state: string;
  created: string;
}

// Interface TelemetryData
export interface TelemetryData {
  charger_id: string;
  timestamp: string;
  value: number;
}

//Combination of Data
export interface CombinedData {
  charger_id: string;
  charger_name: string | null;
  online: boolean;
  state: string;
  last_seen: string;
}

export interface Anomaly {
  anomaly_id: string;
  charger_id: string;
  timestamp: string;
  telemetry_type: string;
  anomaly_type: string;
  anomaly_value: number;
}

export interface FetchContextType {
  //Functions for direct use in Components
  getTelemetryTypes: (chargerId: string) => Promise<string[]>;
  getTelemetryData: (chargerId: string, telemetryKey: string) => Promise<Cpu[]>;
  getAllChargers: () => Promise<Charger[]>;
  getFavorites: (userId: number) => Promise<string[]>;
  toggleFavorite: (
    chargerId: string,
    userId: number,
    isCurrentlyFavorite: boolean
  ) => Promise<void>;
  getCombinedChargerData: (chargers: Charger[]) => Promise<CombinedData[]>;
  getAnomalies: (chargerId: string) => Promise<Anomaly[]>;
  deleteAnomaly: (anomalyId: string) => Promise<void>;
  addAnomaly: (
    chargerId: string,
    timestamp: Date,
    telemetry_type: string,
    anomaly_type: string,
    anomaly_value: number
  ) => Promise<void>;

  //Sync Functions
  syncChargers: () => Promise<void>;
  syncTelemetry: () => Promise<void>;
  syncTelemetryShort: () => Promise<void>;

  //Functions to write Telemetry Data in Context-State
  loadCpuUsage: (chargerId: string) => Promise<void>;
  loadMonitoring: (chargerId: string) => Promise<void>;
  loadCpuThermal: (chargerId: string) => Promise<void>;
  loadAnomalies: (chargerId: string) => Promise<void>;

  // New dynamic telemetry functions
  loadAllTelemetryTypes: (chargerId: string) => Promise<void>;
  getTelemetryCategory: (telemetryType: string) => 'cpu' | 'system' | 'controller' | 'other';

  // State objects - set Telemetry per chargerId
  cpuUsageMap: Record<string, Cpu[]>;
  cpuThermalMap: Record<string, Cpu[]>;
  monitoringMap: Record<string, Monitoring[]>;
  anomaliesMap: Record<string, Anomaly[]>;

  // New dynamic telemetry state
  allTelemetryMap: Record<string, TelemetryTypeData[]>; // chargerId -> array of telemetry types with data
  telemetryTypes: Record<string, string[]>; // chargerId -> array of telemetry type names

  // Simple Error indicator if needed
  searchError: boolean;
}

export const FetchContext = createContext<FetchContextType | undefined>(
  undefined
);

export const FetchProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const [cpuUsageMap, setCpuUsageMap] = useState<Record<string, Cpu[]>>({});
  const [monitoringMap, setMonitoringMap] = useState<
    Record<string, Monitoring[]>
  >({});
  const [cpuThermalMap, setCpuThermalMap] = useState<Record<string, Cpu[]>>({});
  const [anomaliesMap, setAnomaliesMap] = useState<Record<string, Anomaly[]>>({});
  const [searchError, setSearchError] = useState(false);

  // New dynamic telemetry state
  const [allTelemetryMap, setAllTelemetryMap] = useState<Record<string, TelemetryTypeData[]>>({});
  const [telemetryTypes, setTelemetryTypes] = useState<Record<string, string[]>>({});

  // Axios Functions to fetch data from API

  const getTelemetryTypes = useCallback(
    async (chargerId: string): Promise<string[]> => {
      const resp = await apiUtils.get<string[]>(
        API_CONFIG.ENDPOINTS.TELEMETRY.TYPES(chargerId)
      );
      return resp;
    },
    []
  );

  const getTelemetryData = useCallback(
    async (chargerId: string, telemetryKey: string): Promise<Cpu[]> => {
      const resp = await apiUtils.get<Cpu[]>(
        API_CONFIG.ENDPOINTS.TELEMETRY.DATA(chargerId, telemetryKey, 1000)
      );
      return resp;
    },
    []
  );

  const getAllChargers = useCallback(async (): Promise<Charger[]> => {
    const resp = await apiUtils.get<Charger[]>(
      API_CONFIG.ENDPOINTS.CHARGERS.AVAILABLE
    );
    return resp.map((charger) => ({
      ...charger,
      // Prefer live MQTT last-message timestamp when available.
      last_seen: charger.mqtt_last_message ?? charger.last_seen ?? "",
    }));
  }, []);

  const getFavorites = useCallback(
    async (userId: number): Promise<string[]> => {
      const resp = await apiUtils.get<string[]>(
        API_CONFIG.ENDPOINTS.FAVORITES.GET(userId)
      );
      return resp;
    },
    []
  );

  const toggleFavorite = useCallback(
    async (chargerId: string, userId: number, isCurrentlyFavorite: boolean) => {
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

  const getCombinedChargerData = useCallback(
    async (chargers: Charger[]): Promise<CombinedData[]> => {
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
              `Error at values from Charger ${charger.charger_id}`,
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
    },
    []
  );

  const getAnomalies = useCallback(
    async (chargerId: string): Promise<Anomaly[]> => {
      // Use proxy in development, direct URL otherwise
      const resp = await apiUtils.get<Anomaly[]>(
        API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(chargerId)
      );
      return resp;
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
    async (anomalyId: string) => {
      if (!anomalyId) {
        throw new Error("Anomaly ID is required");
      }

      await apiUtils.delete(API_CONFIG.ENDPOINTS.ANOMALIES.DELETE(anomalyId));
    },
    []
  );

  // Sync functions

  const syncChargers = useCallback(async (): Promise<void> => {
    try {
      await apiUtils.post(API_CONFIG.ENDPOINTS.CHARGERS.SYNC, null);
    } catch (err) {
      console.warn("syncChargers failed:", err);
    }
  }, []);

  const syncTelemetry = useCallback(async (): Promise<void> => {
    try {
      await apiUtils.post(
        API_CONFIG.ENDPOINTS.TELEMETRY.SYNC(10000),
        null
      );
    } catch (err) {
      console.warn("syncTelemetry failed:", err);
    }
  }, []);

  const syncTelemetryShort = useCallback(async (): Promise<void> => {
    try {
      await apiUtils.post(
        API_CONFIG.ENDPOINTS.TELEMETRY.SYNC(100),
        null
      );
    } catch (err) {
      console.warn("syncTelemetryShort failed:", err);
    }
  }, []);

  // Functions to write Telemetry Data in Context State

  const loadCpuUsage = useCallback(
    async (chargerId: string) => {
      try {
        // //Sync Telemetry first
        // await syncTelemetryShort();

        // now get the Keys
        const types = await getTelemetryTypes(chargerId);
        const cpuUsageKey = types.find((t) =>
          t.toLowerCase().includes("controllercpuusage")
        );
        if (!cpuUsageKey) {
          console.warn(`Usage-Key for Charger ${chargerId} not found:`, types);
          setSearchError(true);
          return;
        }

        // then get the Data
        const data = await getTelemetryData(chargerId, cpuUsageKey);

        // write the data in the Map
        setCpuUsageMap((prev) => ({
          ...prev,
          [chargerId]: data,
        }));
        setSearchError(false);
      } catch (err) {
        console.error("Error loading CPU Usage:", err);
        setSearchError(true);
      }
    },
    [getTelemetryTypes, getTelemetryData, syncTelemetry]
  );

  const loadCpuThermal = useCallback(
    async (chargerId: string) => {
      try {
        // //Sync Telemetry first
        // await syncTelemetryShort();

        // now get the Keys
        const types = await getTelemetryTypes(chargerId);
        const cpuThermalKey = types.find((t) =>
          t.toLowerCase().includes("controllertemperaturecpu-thermal")
        );
        if (!cpuThermalKey) {
          console.warn(
            `Thermal-Key for Charger ${chargerId} not found:`,
            types
          );
          setSearchError(true);
          return;
        }

        // then get the Data
        const data = await getTelemetryData(chargerId, cpuThermalKey);

        // write the data in the Map
        setCpuThermalMap((prev) => ({
          ...prev,
          [chargerId]: data,
        }));
        setSearchError(false);
      } catch (err) {
        console.error("Error loading CPU Thermal:", err);
        setSearchError(true);
      }
    },
    [getTelemetryTypes, getTelemetryData, syncTelemetry]
  );

  const loadMonitoring = useCallback(async (chargerId: string) => {
    try {
      //  get the Keys
      const types = await getTelemetryTypes(chargerId);
      // filter for keytypes - here all key types without CPU temp and usage
      const keys = types.filter(
        (t) =>
          t.toLowerCase().startsWith("system") ||
          t.toLowerCase().startsWith("controllerstate")
      );
      if (keys.length === 0) {
        console.warn(
          `Key with key value "system" in Charger ${chargerId} not found`,
          types
        );
        setSearchError(true);
        return;
      }

      //  get the Data
      const entries = await Promise.all(
        keys.map(async (key) => {
          const rawData = await getTelemetryData(chargerId, key);
          const data: Monitoring[] = rawData.map((d) => ({
            type: key,
            value: d.value,
          }));
          return [key, data] as const;
        })
      );

      // write the data in the Map
      setMonitoringMap((prev) => ({
        ...prev,
        ...Object.fromEntries(entries),
      }));
      setSearchError(false);
    } catch (err) {
      console.error("Error loading CPU Usage:", err);
      setSearchError(true);
    }
  }, []);

  const loadAnomalies = useCallback(async (chargerId: string) => {
    try {
      const anomalies = await getAnomalies(chargerId);

      // Store anomalies in the Map
      setAnomaliesMap((prev) => ({
        ...prev,
        [chargerId]: anomalies,
      }));
      setSearchError(false);
    } catch (err) {
      console.error("Error loading anomalies:", err);
      setSearchError(true);
    }
  }, [getAnomalies]);

  // New dynamic telemetry functions
  const getTelemetryCategory = useCallback((telemetryType: string): 'cpu' | 'system' | 'controller' | 'other' => {
    const type = telemetryType.toLowerCase();
    if (type.includes('cpu') || type.includes('thermal')) {
      return 'cpu';
    }
    if (type.startsWith('system')) {
      return 'system';
    }
    if (type.startsWith('controller')) {
      return 'controller';
    }
    return 'other';
  }, []);

  const loadAllTelemetryTypes = useCallback(async (chargerId: string) => {
    if (!chargerId) return;

    try {
      setSearchError(false);

      // Get all available telemetry types for this charger
      const types = await getTelemetryTypes(chargerId);
      setTelemetryTypes(prev => ({
        ...prev,
        [chargerId]: types,
      }));

      // Load data for all telemetry types
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
          } catch (error) {
            console.warn(`Failed to load data for telemetry type: ${type}`, error);
            return null;
          }
        })
      );

      // Filter out failed loads and store successful ones
      const successfulData = telemetryData.filter((item): item is TelemetryTypeData => item !== null);
      setAllTelemetryMap(prev => ({
        ...prev,
        [chargerId]: successfulData,
      }));

    } catch (err) {
      console.error("Error loading all telemetry types:", err);
      setSearchError(true);
    }
  }, [getTelemetryTypes, getTelemetryData, getTelemetryCategory]);

  // Provider gives alle the functions etc.
  // Provider gives all the functions etc.

  return (
    <FetchContext.Provider
      value={{
        getTelemetryTypes,
        getTelemetryData,
        getAllChargers,
        getFavorites,
        toggleFavorite,
        getCombinedChargerData,
        getAnomalies,
        addAnomaly,
        deleteAnomaly,
        syncChargers,
        syncTelemetry,
        syncTelemetryShort,
        loadCpuUsage,
        loadMonitoring,
        loadCpuThermal,
        loadAnomalies,
        loadAllTelemetryTypes,
        getTelemetryCategory,
        cpuUsageMap,
        cpuThermalMap,
        anomaliesMap,
        monitoringMap,
        allTelemetryMap,
        telemetryTypes,
        searchError,
      }}
    >
      {children}
    </FetchContext.Provider>
  );
};
