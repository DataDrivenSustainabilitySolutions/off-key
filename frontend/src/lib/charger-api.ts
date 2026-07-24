import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { clientLogger } from "@/lib/logger";
import type {
  Anomaly,
  Charger,
  TelemetryDataPoint,
  TelemetryTypeData,
} from "@/types/charger";
import {
  getTelemetryCategory,
  normalizeChargerLastSeen,
} from "@/types/charger";

export const getTelemetryTypes = (chargerId: string): Promise<string[]> =>
  apiUtils.get<string[]>(API_CONFIG.ENDPOINTS.TELEMETRY.TYPES(chargerId));

export const getTelemetryData = (
  chargerId: string,
  telemetryType: string,
): Promise<TelemetryDataPoint[]> =>
  apiUtils.get<TelemetryDataPoint[]>(
    API_CONFIG.ENDPOINTS.TELEMETRY.DATA(chargerId, telemetryType, 1000),
  );

export const getAllTelemetryData = async (
  chargerId: string,
): Promise<TelemetryTypeData[]> => {
  const telemetryTypes = await getTelemetryTypes(chargerId);
  const telemetryData = await Promise.all(
    telemetryTypes.map(async (type): Promise<TelemetryTypeData | null> => {
      try {
        return {
          type,
          category: getTelemetryCategory(type),
          data: await getTelemetryData(chargerId, type),
        };
      } catch (error) {
        clientLogger.warn({
          event: "telemetry.type_load_failed",
          message: "Failed to load data for telemetry type",
          error,
          context: { chargerId, telemetryType: type },
        });
        return null;
      }
    }),
  );

  return telemetryData.filter(
    (item): item is TelemetryTypeData => item !== null,
  );
};

export const getAllChargers = async (): Promise<Charger[]> => {
  const chargers = await apiUtils.get<Charger[]>(
    API_CONFIG.ENDPOINTS.CHARGERS.AVAILABLE,
  );
  return chargers.map(normalizeChargerLastSeen);
};

export const getFavorites = (userId: number): Promise<string[]> =>
  apiUtils.get<string[]>(API_CONFIG.ENDPOINTS.FAVORITES.GET(userId));

export const toggleFavorite = async (
  chargerId: string,
  userId: number,
  isCurrentlyFavorite: boolean,
): Promise<void> => {
  const body = { charger_id: chargerId, user_id: userId };
  if (isCurrentlyFavorite) {
    await apiUtils.delete(API_CONFIG.ENDPOINTS.FAVORITES.REMOVE, body);
    return;
  }
  await apiUtils.post(API_CONFIG.ENDPOINTS.FAVORITES.ADD, body);
};

export const getAnomalies = (chargerId: string): Promise<Anomaly[]> =>
  apiUtils.get<Anomaly[]>(
    API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(chargerId),
  );

export const getAnomalyCount = async (since?: string): Promise<number> => {
  const endpoint = since
    ? `${API_CONFIG.ENDPOINTS.ANOMALIES.COUNT}?since=${encodeURIComponent(since)}`
    : API_CONFIG.ENDPOINTS.ANOMALIES.COUNT;
  const response = await apiUtils.get<{ count: number }>(endpoint);
  return response.count;
};

export const deleteAnomaly = async (anomalyId: string): Promise<void> => {
  if (!anomalyId) {
    throw new Error("Anomaly ID is required");
  }
  await apiUtils.delete(API_CONFIG.ENDPOINTS.ANOMALIES.DELETE(anomalyId));
};
