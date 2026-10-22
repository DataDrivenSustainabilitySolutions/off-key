import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { drainForward, TELEMETRY_PAGE_SIZE } from "@/lib/forward-pages";
import { clientLogger } from "@/lib/logger";
import type {
  Anomaly,
  Charger,
  TelemetryDataPoint,
  TelemetryCursor,
  TelemetryTypeData,
} from "@/types/charger";
import { normalizeChargerLastSeen } from "@/types/charger";
import type { SystemSnapshot } from "@/features/catalogue/systemTypes";

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
  // A loaded catalogue snapshot saves fetching /v1/system on every refresh.
  catalogue?: Pick<SystemSnapshot, "document" | "runtime">,
): Promise<TelemetryTypeData[]> => {
  const [telemetryTypes, snapshot] = await Promise.all([
    getTelemetryTypes(chargerId, signal),
    catalogue ?? get<SystemSnapshot>("/v1/system", signal),
  ]);
  const definitions = new Map(
    snapshot.document.streams.flatMap(stream => {
      const binding = snapshot.runtime.bindings?.[stream.id];
      return binding?.entity_id === chargerId ? [[binding.telemetry_key, stream] as const] : [];
    }),
  );
  const telemetryData = await Promise.all(
    telemetryTypes.map(async (type): Promise<TelemetryTypeData | null> => {
      try {
        const data = await drainForward({
          cursor: cursorByType?.get(type),
          fetchPage: cursor => getTelemetryData(chargerId, type, signal, cursor),
          cursorOf: getTelemetryCursor,
          pageSize: TELEMETRY_PAGE_SIZE,
        });
        const nextCursor = getTelemetryCursor(data);
        return {
          type,
          category: definitions.get(type)?.category ?? "Other",
          ...(definitions.get(type)?.label && { label: definitions.get(type)!.label }),
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
