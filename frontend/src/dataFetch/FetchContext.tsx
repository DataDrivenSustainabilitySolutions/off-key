import React, { createContext, useState, useCallback, ReactNode } from "react";
import axios from "axios";

// Interface CPU
export interface Cpu {
  timestamp: string;
  value: number;
}

export interface Monitoring {
  type: string;
  value: number;
}
// Interface Charger
export interface Charger {
  charger_name: string | null;
  last_seen: string;
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

  //Sync Functions
  syncChargers: () => Promise<void>;
  syncTelemetry: () => Promise<void>;
  syncTelemetryShort: () => Promise<void>;

  //Functions to write Telemetry Data in Context-State
  loadCpuUsage: (chargerId: string) => Promise<void>;
  loadMonitoring: (chargerId: string) => Promise<void>;
  loadCpuThermal: (chargerId: string) => Promise<void>;

  // State objects - set Telemetry per chargerId
  cpuUsageMap: Record<string, Cpu[]>;
  cpuThermalMap: Record<string, Cpu[]>;
  monitoringMap: Record<string, Monitoring[]>;
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
  const [searchError, setSearchError] = useState(false);

  // Axios Functions to fetch data from API

  const getTelemetryTypes = useCallback(
    async (chargerId: string): Promise<string[]> => {
      const resp = await axios.get<string[]>(
        `http://127.0.0.1:8000/v1/telemetry/${chargerId}/type`
      );
      return resp.data;
    },
    []
  );

  const getTelemetryData = useCallback(
    async (chargerId: string, telemetryKey: string): Promise<Cpu[]> => {
      const resp = await axios.get<Cpu[]>(
        `http://127.0.0.1:8000/v1/telemetry/${chargerId}/${telemetryKey}?limit=1000`
      );
      return resp.data;
    },
    []
  );

  const getAllChargers = useCallback(async (): Promise<Charger[]> => {
    const resp = await axios.get<Charger[]>(
      "http://127.0.0.1:8000/v1/chargers/available"
    );
    return resp.data;
  }, []);

  const getFavorites = useCallback(
    async (userId: number): Promise<string[]> => {
      const resp = await axios.get<string[]>(
        `http://127.0.0.1:8000/v1/favorites?user_id=${userId}`
      );
      return resp.data;
    },
    []
  );

  const toggleFavorite = useCallback(
    async (chargerId: string, userId: number, isCurrentlyFavorite: boolean) => {
      if (isCurrentlyFavorite) {
        await axios.delete("http://127.0.0.1:8000/v1/favorites", {
          data: { charger_id: chargerId, user_id: userId },
        });
      } else {
        await axios.post("http://127.0.0.1:8000/v1/favorites", {
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
              axios.get<TelemetryData[]>(
                `http://127.0.0.1:8000/v1/telemetry/${charger.charger_id}/controllerCpuUsage`
              ),
              axios.get<TelemetryData[]>(
                `http://127.0.0.1:8000/v1/telemetry/${charger.charger_id}/controllertemperaturecpu-thermal`
              ),
            ]);
            return {
              charger_id: charger.charger_id,
              charger_name: charger.charger_name,
              online: charger.online,
              state: charger.state,
              last_seen: charger.last_seen,
              value1: value1Res.data[0]?.value ?? null,
              value2: value2Res.data[0]?.value ?? null,
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

  // Sync functions

  const syncChargers = useCallback(async (): Promise<void> => {
    try {
      await axios.post("http://127.0.0.1:8000/v1/chargers/sync", null);
    } catch (err) {
      console.warn("syncChargers failed:", err);
    }
  }, []);

  const syncTelemetry = useCallback(async (): Promise<void> => {
    try {
      await axios.post(
        "http://127.0.0.1:8000/v1/telemetry/sync?limit=10000",
        null
      );
    } catch (err) {
      console.warn("syncTelemetry failed:", err);
    }
  }, []);

  const syncTelemetryShort = useCallback(async (): Promise<void> => {
    try {
      await axios.post(
        "http://127.0.0.1:8000/v1/telemetry/sync?limit=100",
        null
      );
    } catch (err) {
      console.warn("syncTelemetryShort failed:", err);
    }
  }, []);

  // ─── 3) Neu: Funktionen, um Telemetrie‐Daten in den Context‐State zu schreiben ───
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

  // Provider gives alle the functions etc.

  return (
    <FetchContext.Provider
      value={{
        getTelemetryTypes,
        getTelemetryData,
        getAllChargers,
        getFavorites,
        toggleFavorite,
        getCombinedChargerData,
        syncChargers,
        syncTelemetry,
        syncTelemetryShort,
        loadCpuUsage,
        loadMonitoring,
        loadCpuThermal,
        cpuUsageMap,
        cpuThermalMap,
        monitoringMap,
        searchError,
      }}
    >
      {children}
    </FetchContext.Provider>
  );
};
