import type { TelemetryDataPoint } from "@/types/charger";
import { epochMicroseconds } from "@/lib/timestamps";

export type TimeValue = [epochMilliseconds: number, value: number];

/** Keep the last finite sample at each valid timestamp, in chronological order. */
export const normalizeTelemetry = (points: readonly TelemetryDataPoint[]): TimeValue[] => {
  const valuesByTime = new Map<bigint, number>();
  for (const point of points) {
    const time = epochMicroseconds(point.timestamp);
    if (time === undefined || !Number.isFinite(point.value)) continue;
    valuesByTime.set(time, point.value);
  }
  return [...valuesByTime.entries()]
    .sort(([left], [right]) => left === right ? 0 : left < right ? -1 : 1)
    .map(([time, value]) => [Number(time) / 1000, value]);
};

/** A pause this many times the usual spacing, such as one a Gate holds back, breaks a line. */
const PAUSE_FACTOR = 5;

/** The longest step between sorted times that a line still bridges: a multiple of the median step. */
export const getPauseLimit = (times: readonly number[]): number => {
  const steps = times.slice(1).map((time, index) => time - times[index]!).filter((step) => step > 0).sort((a, b) => a - b);
  const median = steps[Math.floor(steps.length / 2)];
  return median === undefined ? Number.POSITIVE_INFINITY : median * PAUSE_FACTOR;
};
