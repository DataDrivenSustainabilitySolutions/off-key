import type { TelemetryDataPoint } from "@/types/charger";

export type ReadingMonitoringBinding = { entityId: string; telemetryType: string };

export function mergeReadingHistory(
  current: readonly TelemetryDataPoint[],
  incoming: readonly TelemetryDataPoint[],
  limit = 4096,
): TelemetryDataPoint[] {
  const points = new Map<number, TelemetryDataPoint>();
  for (const point of [...current, ...incoming]) {
    const time = Date.parse(point.timestamp);
    if (Number.isFinite(time) && Number.isFinite(point.value)) points.set(time, point);
  }
  return [...points.entries()].sort(([left], [right]) => left - right)
    .slice(-limit).map(([, point]) => point);
}
