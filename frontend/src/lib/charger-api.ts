import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { drainForward, TELEMETRY_PAGE_SIZE } from "@/lib/forward-pages";
import { clientLogger } from "@/lib/logger";
import type {
  Anomaly,
  AnomalyPage,
  AnomalyQuery,
  TelemetryDataPoint,
  TelemetryCursor,
  TelemetryTypeData,
} from "@/types/charger";
import type { SystemStream } from "@/types/system";

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

/** Stored history downsampled to each bucket's extremes; no startMs means all of it. */
export const getTelemetryRange = (
  readingId: string,
  range: { startMs?: number; endMs?: number; buckets?: number },
  signal?: AbortSignal,
): Promise<TelemetryDataPoint[]> =>
  get<TelemetryDataPoint[]>(API_CONFIG.ENDPOINTS.READINGS.BUCKETS(readingId, range), signal);

/** Recorded values of one catalogue reading; a cursor returns those that arrived since. */
export const getTelemetryData = (
  readingId: string,
  signal?: AbortSignal,
  cursor?: TelemetryCursor,
): Promise<TelemetryApiPoint[]> =>
  get<TelemetryApiPoint[]>(
    API_CONFIG.ENDPOINTS.READINGS.MEASUREMENTS(readingId, TELEMETRY_PAGE_SIZE, cursor),
    signal,
  );

/** The recorded values of each catalogue reading, one series per reading id. */
export const getAllTelemetryData = async (
  readings: readonly Pick<SystemStream, "id" | "label" | "category">[],
  signal?: AbortSignal,
  cursorByReading?: ReadonlyMap<string, TelemetryCursor>,
): Promise<TelemetryTypeData[]> => {
  const series = await Promise.all(readings.map(async (reading) => {
    try {
      const data = await drainForward({
        cursor: cursorByReading?.get(reading.id),
        fetchPage: cursor => getTelemetryData(reading.id, signal, cursor),
        cursorOf: getTelemetryCursor,
        pageSize: TELEMETRY_PAGE_SIZE,
      });
      const nextCursor = getTelemetryCursor(data);
      return {
        type: reading.id,
        category: reading.category || "Other",
        ...(reading.label && { label: reading.label }),
        data: data.map(({ timestamp, value }) => ({ timestamp, value })),
        ...(nextCursor && { cursor: nextCursor }),
      };
    } catch (error) {
      clientLogger.warn({
        event: "telemetry.reading_load_failed",
        message: "Failed to load the values of a reading",
        error,
        context: { readingId: reading.id },
      });
      return null;
    }
  }));
  return series.filter(item => item !== null);
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
    if (!series) return existing;
    if (series.data.length === 0) {
      return series.category === existing.category && series.label === existing.label
        ? existing
        : { ...existing, category: series.category, label: series.label };
    }

    const points = new Map(existing.data.map((point) => [point.timestamp, point]));
    series.data.forEach((point) => points.set(point.timestamp, point));
    return {
      ...series,
      // Parse each timestamp once instead of twice per comparison.
      data: [...points.values()]
        .map((point) => ({ point, time: Date.parse(point.timestamp) }))
        .sort((left, right) => right.time - left.time)
        .slice(0, limit)
        .map(({ point }) => point),
    };
  });
  merged.push(...incomingByType.values());

  return merged.length === current.length &&
    merged.every((series, index) => series === current[index])
    ? current
    : merged;
};

/** Reporting's alarms, scoped and filtered on the server. */
export const queryAnomalies = (query: AnomalyQuery, signal?: AbortSignal): Promise<AnomalyPage> =>
  apiUtils.post<AnomalyPage>(API_CONFIG.ENDPOINTS.ANOMALIES.QUERY, query, signal ? { signal } : undefined);

export const getAnomalies = (
  chargerId: string,
  signal?: AbortSignal,
): Promise<Anomaly[]> =>
  get<Anomaly[]>(
    API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(chargerId),
    signal,
  );

export const deleteAnomaly = async (anomalyId: string): Promise<void> => {
  if (!anomalyId) {
    throw new Error("Anomaly ID is required");
  }
  await apiUtils.delete(API_CONFIG.ENDPOINTS.ANOMALIES.DELETE(anomalyId));
};
