import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { clientLogger } from "@/lib/logger";
import type {
  Anomaly,
  Charger,
  TelemetryDataPoint,
  TelemetryCursor,
  TelemetryTypeData,
} from "@/types/charger";
import {
  getTelemetryCategory,
  normalizeChargerLastSeen,
} from "@/types/charger";

const TELEMETRY_PAGE_SIZE = 1000;
const MAX_FORWARD_PAGES = 10;
type TelemetryApiPoint = TelemetryDataPoint & { created?: string };

export const getTelemetryCursor = (
  points: TelemetryApiPoint[],
): TelemetryCursor | undefined =>
  points.reduce<TelemetryCursor | undefined>((latest, point) => {
    if (!point.created) return latest;
    const createdTime = Date.parse(point.created);
    const eventTime = Date.parse(point.timestamp);
    if (!Number.isFinite(createdTime) || !Number.isFinite(eventTime)) return latest;
    const cursor = { created: point.created, timestamp: point.timestamp };
    if (!latest) return cursor;
    const createdDifference = createdTime - Date.parse(latest.created);
    if (createdDifference > 0) return cursor;
    if (createdDifference < 0) return latest;
    return eventTime > Date.parse(latest.timestamp)
      ? cursor
      : latest;
  }, undefined);

const get = <T>(endpoint: string, signal?: AbortSignal): Promise<T> =>
  signal
    ? apiUtils.get<T>(endpoint, { signal })
    : apiUtils.get<T>(endpoint);

export const getTelemetryTypes = (
  chargerId: string,
  signal?: AbortSignal,
): Promise<string[]> =>
  get<string[]>(API_CONFIG.ENDPOINTS.TELEMETRY.TYPES(chargerId), signal);

export const getTelemetryData = (
  chargerId: string,
  telemetryType: string,
  signal?: AbortSignal,
  cursor?: TelemetryCursor,
): Promise<TelemetryApiPoint[]> =>
  get<TelemetryApiPoint[]>(
    API_CONFIG.ENDPOINTS.TELEMETRY.DATA(
      chargerId,
      telemetryType,
      TELEMETRY_PAGE_SIZE,
      cursor,
    ),
    signal,
  );

export const getAllTelemetryData = async (
  chargerId: string,
  signal?: AbortSignal,
  cursorByType?: ReadonlyMap<string, TelemetryCursor>,
): Promise<TelemetryTypeData[]> => {
  const telemetryTypes = await getTelemetryTypes(chargerId, signal);
  const telemetryData = await Promise.all(
    telemetryTypes.map(async (type): Promise<TelemetryTypeData | null> => {
      try {
        const initialCursor = cursorByType?.get(type);
        let cursor = initialCursor;
        const data: TelemetryApiPoint[] = [];
        for (let pageNumber = 0; pageNumber < MAX_FORWARD_PAGES; pageNumber += 1) {
          const page = await getTelemetryData(chargerId, type, signal, cursor);
          data.push(...page);
          if (!initialCursor || page.length < TELEMETRY_PAGE_SIZE) break;
          const nextCursor = getTelemetryCursor(page);
          if (
            !nextCursor ||
            (nextCursor.created === cursor?.created &&
              nextCursor.timestamp === cursor.timestamp)
          ) break;
          cursor = nextCursor;
        }
        const nextCursor = getTelemetryCursor(data);
        return {
          type,
          category: getTelemetryCategory(type),
          data: data.map(({ timestamp, value }) => ({ timestamp, value })),
          ...(nextCursor && { cursor: nextCursor }),
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

export const mergeTelemetryData = (
  current: TelemetryTypeData[],
  incoming: TelemetryTypeData[],
  limit = 1000,
): TelemetryTypeData[] => {
  const incomingByType = new Map(incoming.map((series) => [series.type, series]));
  const merged = current.map((existing) => {
    const series = incomingByType.get(existing.type);
    incomingByType.delete(existing.type);
    if (!series || series.data.length === 0) return existing;

    const points = new Map(existing.data.map((point) => [point.timestamp, point]));
    series.data.forEach((point) => points.set(point.timestamp, point));
    return {
      ...series,
      data: [...points.values()]
        .sort((left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp))
        .slice(0, limit),
    };
  });
  merged.push(...incomingByType.values());

  return merged.length === current.length &&
    merged.every((series, index) => series === current[index])
    ? current
    : merged;
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

export const getAnomalies = (
  chargerId: string,
  signal?: AbortSignal,
): Promise<Anomaly[]> =>
  get<Anomaly[]>(
    API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(chargerId),
    signal,
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
