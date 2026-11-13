import { getTelemetryRange } from '@/lib/charger-api';
import { epochMilliseconds } from '@/lib/timestamps';

/** Keep the exact scored input even when the surrounding window is downsampled. */
export async function getEventReadings(id: string, range: { startMs?: number; endMs?: number },
  inputTime: string | null | undefined, signal: AbortSignal) {
  const points = await getTelemetryRange(id, { ...range, buckets: 600 }, signal);
  const time = inputTime ? epochMilliseconds(inputTime) : NaN;
  if (!Number.isFinite(time) || time < (range.startMs ?? -Infinity) || time > (range.endMs ?? Infinity)
    || points.some(point => epochMilliseconds(point.timestamp) === time)) return points;
  // Fetch the stored sample, preserving its microsecond identity; never interpolate it.
  const exact = await getTelemetryRange(id, { startMs: time, endMs: time + 0.001, buckets: 1 }, signal);
  return [...points, ...exact.filter(point => epochMilliseconds(point.timestamp) === time)]
    .sort((left, right) => epochMilliseconds(left.timestamp) - epochMilliseconds(right.timestamp));
}
