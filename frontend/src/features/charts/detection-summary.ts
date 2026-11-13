import type { DetectorInputSeries, ForecastPoint } from "./detector-inputs";
import { isDense } from "./history-presentation";
import type { DetectionChartPoint, SecondaryChartSeries } from "./telemetry-detectors";

type Bin = { sum: number; count: number; minimum: number; maximum: number };

/** Calls `step` per interval in time order, with the interval's middle and the middle of any empty stretch before it. */
function eachInterval<B>(bins: Map<number, B>, intervalMs: number, step: (time: number, bin: B, gap?: number) => void) {
  let previous: number | undefined;
  for (const [key, bin] of [...bins].sort(([left], [right]) => left - right)) {
    step((key + .5) * intervalMs, bin, previous !== undefined && key - previous > 1 ? (previous + 1 + key) / 2 * intervalMs : undefined);
    previous = key;
  }
}

/**
 * The window cuts its first interval and the newest one is still filling: a statistic of
 * a few results jumps about at the edge. An edge interval holding less than half the
 * usual count joins its neighbour, as a reading's does.
 */
function settledIntervals(times: readonly number[], intervalMs: number): (time: number) => number {
  const counts = new Map<number, number>();
  for (const time of times) { const key = Math.floor(time / intervalMs); counts.set(key, (counts.get(key) ?? 0) + 1); }
  const keys = [...counts.keys()].sort((left, right) => left - right);
  const usual = [...counts.values()].sort((left, right) => left - right)[counts.size >> 1] ?? 0;
  const joined = new Map<number, number>();
  const join = (edge: number | undefined, neighbour: number | undefined) => {
    if (edge !== undefined && neighbour !== undefined && Math.abs(edge - neighbour) === 1 && counts.get(edge)! * 2 < usual) joined.set(edge, neighbour);
  };
  if (keys.length >= 3) { join(keys[keys.length - 1], keys[keys.length - 2]); join(keys[0], keys[1]); }
  return time => { const key = Math.floor(time / intervalMs); return joined.get(key) ?? key; };
}

/**
 * A score is judged by its peaks, so each interval keeps its highest evaluated
 * result: a mean would average an alarm away. The kept point is a recorded
 * observation, so its threshold, alarm state and inputs stay exact. An alarm
 * outranks a higher quiet score, and evidence above the plotted range both.
 */
function peakSeries(series: SecondaryChartSeries, intervalMs: number): SecondaryChartSeries {
  const boundaries = new Map(series.overflow.map(({ observation, boundary }) => [observation, boundary]));
  const weight = ({ value, observation }: DetectionChartPoint) => boundaries.get(observation!) === "upper" ? 3
    : value[1] === null ? 0 : (observation!.alarmFired ?? observation!.alarmActive) || observation!.alarmMuted ? 2 : 1;
  const intervalOf = settledIntervals(series.data.flatMap(point => point.observation ? [point.value[0]] : []), intervalMs);
  const data: DetectionChartPoint[] = [];
  let bucket: number | undefined, best: DetectionChartPoint | undefined, count = 0;
  const close = () => {
    if (best) data.push({ ...best, peak: { count } });
    best = undefined; count = 0;
  };
  for (const point of series.data) {
    // Pause markers are derived again here: interval results break across an empty interval.
    if (!point.observation) continue;
    const next = intervalOf(point.value[0]);
    if (next !== bucket) {
      close();
      if (bucket !== undefined && next - bucket > 1) data.push({ value: [(bucket + 1 + next) / 2 * intervalMs, null] });
      bucket = next;
    }
    count++;
    const rank = weight(point), leading = best ? weight(best) : -1;
    if (rank > leading || (rank === leading && (point.value[1] ?? -Infinity) > (best!.value[1] ?? -Infinity))) best = point;
  }
  close();
  const kept = new Set(data.map(point => point.observation));
  return { ...series, data, overflow: series.overflow.filter(({ observation }) => kept.has(observation)) };
}

/** What a forecaster expected, averaged over the same intervals as the feature it is compared with. */
function meanForecast(points: readonly ForecastPoint[], intervalMs: number, intervalOf: (time: number) => number): ForecastPoint[] {
  const bins = new Map<number, { sums: number[]; counts: number[] }>();
  for (const [time, ...values] of points) {
    if (values[0] === null) continue;
    const key = intervalOf(time);
    const bin = bins.get(key) ?? { sums: [0, 0, 0], counts: [0, 0, 0] };
    values.forEach((value, index) => { if (value !== null) { bin.sums[index]! += value; bin.counts[index]!++; } });
    bins.set(key, bin);
  }
  const result: ForecastPoint[] = [];
  eachInterval(bins, intervalMs, (time, { sums, counts }, gap) => {
    if (gap !== undefined) result.push([gap, null, null, null]);
    const mean = (index: number) => counts[index] ? sums[index]! / counts[index]! : null;
    result.push([time, mean(0), mean(1), mean(2)]);
  });
  return result;
}

/** A feature keeps its mean and observed range per interval, like a reading. */
function meanInputs(series: DetectorInputSeries, intervalMs: number): DetectorInputSeries {
  const intervalOf = settledIntervals(series.data.flatMap(([time, value]) => value === null ? [] : [time]), intervalMs);
  const bins = new Map<number, Bin>();
  for (const [time, value] of series.data) {
    if (value === null) continue;
    const key = intervalOf(time);
    const bin = bins.get(key) ?? { sum: 0, count: 0, minimum: value, maximum: value };
    bin.sum += value; bin.count++; bin.minimum = Math.min(bin.minimum, value); bin.maximum = Math.max(bin.maximum, value);
    bins.set(key, bin);
  }
  const data: DetectorInputSeries["data"] = [], range: NonNullable<DetectorInputSeries["range"]> = [];
  eachInterval(bins, intervalMs, (time, bin, gap) => {
    if (gap !== undefined) { data.push([gap, null]); range.push([gap, null, null]); }
    data.push([time, bin.sum / bin.count]); range.push([time, bin.minimum, bin.maximum]);
  });
  return { ...series, data, range, ...(series.forecast ? { forecast: meanForecast(series.forecast, intervalMs, intervalOf) } : {}) };
}

/**
 * Dense score and feature panes follow their reading into intervals, each with the
 * statistic its meaning needs: a score its peak, a feature its mean and range.
 * Sparse series stay as recorded, and so does everything when `intervalMs` is 0 (Raw).
 * `shown` is the inspected span of time: density is judged by what it holds.
 */
export function summarizeDetection<T extends { secondarySeries: SecondaryChartSeries[]; detectorInputs?: DetectorInputSeries[] }>(
  model: T, intervalMs: number, buckets: number, shown?: readonly [startMs: number, endMs: number]): T {
  if (!(intervalMs > 0)) return model;
  const dense = (times: number[]) => isDense(shown ? times.filter(time => time >= shown[0] && time <= shown[1]).length : times.length, buckets);
  return { ...model,
    secondarySeries: model.secondarySeries.map(series =>
      dense(series.data.flatMap(point => point.observation ? [point.value[0]] : [])) ? peakSeries(series, intervalMs) : series),
    ...(model.detectorInputs ? { detectorInputs: model.detectorInputs.map(series =>
      dense(series.data.flatMap(([time, value]) => value === null ? [] : [time])) ? meanInputs(series, intervalMs) : series) } : {}),
  };
}
