import type { TelemetryDataPoint } from "@/types/charger";
import { epochMicroseconds } from "@/lib/timestamps";

/** A catalogue reading that records, so it has history to poll. */
export type ReadingMonitoringBinding = { readingId: string };

export function mergeReadingHistory(
  current: readonly TelemetryDataPoint[],
  incoming: readonly TelemetryDataPoint[],
  limit = 4096,
): TelemetryDataPoint[] {
  const points = new Map<bigint, TelemetryDataPoint>();
  for (const point of [...current, ...incoming]) {
    const time = epochMicroseconds(point.timestamp);
    if (time !== undefined && Number.isFinite(point.value)) points.set(time, point);
  }
  return [...points.entries()].sort(([left], [right]) => left === right ? 0 : left < right ? -1 : 1)
    .slice(-limit).map(([, point]) => point);
}
