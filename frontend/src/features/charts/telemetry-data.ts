import type { TelemetryDataPoint } from "@/types/charger";

export type TimeValue = [epochMilliseconds: number, value: number];

/** Keep the last finite sample at each valid timestamp, in chronological order. */
export const normalizeTelemetry = (points: readonly TelemetryDataPoint[]): TimeValue[] => {
  const valuesByTime = new Map<number, number>();
  for (const point of points) {
    const time = Date.parse(point.timestamp);
    if (!Number.isFinite(time) || !Number.isFinite(point.value)) continue;
    valuesByTime.set(time, point.value);
  }
  return [...valuesByTime.entries()].sort((left, right) => left[0] - right[0]);
};
