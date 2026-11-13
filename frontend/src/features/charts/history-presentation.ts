import type { LineSeriesOption } from "echarts/charts";
import type { HistoryPoint, HistoryPreference, TelemetryHistory } from "@/types/telemetry-history";
import { epochMilliseconds, isoTimestamp } from "@/lib/timestamps";
import { getPauseLimit, type TimeValue } from "./telemetry-data";

export const DEFAULT_HISTORY_PREFERENCE: HistoryPreference = { mode: "auto" };
const DAY = 86_400_000;
const INTERVALS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 15000,
  30000, 60000, 120000, 300000, 600000, 900000, 1800000, 3600000, 7200000, 21600000, 43200000, DAY];

export const intervalLabel = (ms: number): string => ms < 1000 ? `${ms}ms`
  : ms < 60000 ? `${ms / 1000}s` : ms < 3600000 ? `${ms / 60000}m`
  : ms < DAY ? `${ms / 3600000}h` : `${ms / DAY}d`;

/** The readable interval that fits a span into `buckets` means, as the server chooses it. */
export const historyInterval = (spanMs: number, buckets: number, minimumMs = 0): number => {
  const target = Math.max(1, spanMs / buckets, minimumMs);
  return INTERVALS.find(value => value >= target) ?? Math.ceil(target / DAY) * DAY;
};

/** A series is summarised once its samples outnumber what the width can separate. */
export const isDense = (samples: number, buckets: number): boolean => samples > buckets * 2;

/**
 * Only call with original readings, never the historical min/max overview. A chart
 * with several panes passes one `intervalMs`, so their buckets line up.
 */
export function presentHistory(data: TimeValue[], preference: HistoryPreference, buckets: number,
  range?: readonly [number, number], intervalMs?: number): TelemetryHistory {
  const visible = range ? data.filter(([time]) => time >= range[0] && time <= range[1]) : data;
  const first = visible[0]?.[0], last = visible[visible.length - 1]?.[0];
  const history: TelemetryHistory = { representation: "raw", points: visible.map(([time, value]) => ({ timestamp: isoTimestamp(time), value })),
    interval_ms: 0, sample_count: visible.length, extent: first !== undefined && last !== undefined ? [isoTimestamp(first), isoTimestamp(last)] : null, truncated: false };
  if (first === undefined || last === undefined || preference.mode === "raw"
    || (!preference.windowMs && !isDense(visible.length, buckets))) return history;
  const interval = intervalMs ?? historyInterval((range?.[1] ?? last) - (range?.[0] ?? first), buckets, preference.windowMs);
  const bins = new Map<number, { sum: number; minimum: number; maximum: number; count: number }>();
  for (const [time, value] of visible) {
    const start = Math.floor(time / interval) * interval;
    const bin = bins.get(start) ?? { sum: 0, minimum: value, maximum: value, count: 0 };
    bin.sum += value; bin.count++; bin.minimum = Math.min(bin.minimum, value); bin.maximum = Math.max(bin.maximum, value);
    bins.set(start, bin);
  }
  return { ...history, representation: "mean", interval_ms: interval,
    points: [...bins].map(([start, bin]) => {
      const left = Math.max(start, range?.[0] ?? first), right = Math.min(start + interval, range?.[1] ?? last);
      return { timestamp: isoTimestamp((left + right) / 2), value: bin.sum / bin.count,
        minimum: bin.minimum, maximum: bin.maximum, count: bin.count, start: isoTimestamp(left), end: isoTimestamp(right) };
    }) };
}

/** Detail replaces the overview within its viewport; context outside stays in the navigator. */
export function combineHistory(overview: TelemetryHistory | undefined, detail: TelemetryHistory,
  range?: { startMs: number; endMs: number }): TelemetryHistory {
  if (!overview || !range) return detail;
  const outside = overview.points.filter(point => {
    const start = epochMilliseconds(point.start ?? point.timestamp), end = epochMilliseconds(point.end ?? point.timestamp);
    return end < range.startMs || start > range.endMs;
  });
  return { ...detail, extent: overview.extent, points: [...outside, ...detail.points]
    .sort((a, b) => epochMilliseconds(a.timestamp) - epochMilliseconds(b.timestamp)) };
}

type Span = [startMs: number, endMs: number];
const spanOf = (point: HistoryPoint): Span | undefined => point.start && point.end
  ? [epochMilliseconds(point.start), epochMilliseconds(point.end)] : undefined;

/**
 * The window clips its first and last bucket, and the newest one is still filling:
 * a mean of a few readings jumps about and draws a spike at the edge. An edge
 * bucket holding less than half the usual count joins its neighbour. Display
 * only; the history itself keeps every bucket.
 */
function settleEdges(points: HistoryPoint[]): HistoryPoint[] {
  const counts = points.flatMap(point => point.count === undefined ? [] : [point.count]).sort((a, b) => a - b);
  const usual = counts[counts.length >> 1];
  if (usual === undefined || counts.length < 3) return points;
  const thin = (point?: HistoryPoint) => point?.count !== undefined && point.count * 2 < usual;
  const join = (left?: HistoryPoint, right?: HistoryPoint): HistoryPoint | undefined => {
    const before = left && spanOf(left), after = right && spanOf(right);
    if (!before || !after || before[1] !== after[0] || left!.count === undefined || right!.count === undefined) return undefined;
    const count = left!.count + right!.count;
    return { timestamp: isoTimestamp((before[0] + after[1]) / 2), value: (left!.value * left!.count + right!.value * right!.count) / count,
      minimum: Math.min(left!.minimum!, right!.minimum!), maximum: Math.max(left!.maximum!, right!.maximum!), count,
      start: left!.start, end: right!.end };
  };
  let settled = points;
  const newest = thin(settled[settled.length - 1]) ? join(settled[settled.length - 2], settled[settled.length - 1]) : undefined;
  if (newest) settled = [...settled.slice(0, -2), newest];
  const oldest = thin(settled[0]) ? join(settled[0], settled[1]) : undefined;
  if (oldest) settled = [oldest, ...settled.slice(2)];
  return settled;
}

export type HistoryChartPoint = { value: [number, number | null]; summary?: HistoryPoint };
export function historyChartData(history: TelemetryHistory): HistoryChartPoint[] {
  const points = settleEdges(history.points);
  const times = points.map(point => epochMilliseconds(point.timestamp));
  const spans = points.map(spanOf);
  const pauseLimit = getPauseLimit(times);
  const at = (index: number, time = times[index]!): HistoryChartPoint =>
    ({ value: [time, points[index]!.value], ...(points[index]!.count !== undefined ? { summary: points[index] } : {}) });
  const result: HistoryChartPoint[] = [];
  let from = 0;
  for (let index = 1; index <= points.length; index++) {
    const before = spans[index - 1], after = spans[index];
    // Means break across an empty bucket; original samples across a pause.
    if (index < points.length && !(before && after ? after[0] > before[1] : times[index]! - times[index - 1]! > pauseLimit)) continue;
    // A mean stands for its whole interval, so a run reaches the outer edges of its
    // first and last bucket. A bucket between two gaps then still draws its width.
    const run: HistoryChartPoint[] = [];
    const head = spans[from], tail = spans[index - 1];
    if (head && head[0] < times[from]!) run.push(at(from, head[0]));
    for (let position = from; position < index; position++) run.push(at(position));
    if (tail && tail[1] > times[index - 1]!) run.push(at(index - 1, tail[1]));
    result.push(...run);
    if (index < points.length) result.push({ value: [((before?.[1] ?? times[index - 1]!) + (after?.[0] ?? times[index]!)) / 2, null] });
    from = index;
  }
  return result;
}

/** One series' lowest and highest value at each drawn time; null breaks the band. */
export type BandPoint = readonly [time: number, minimum: number | null, maximum: number | null];

/** Two stacked, silent lines draw the observed range, including negative readings. */
export function bandSeries(id: string, data: readonly BandPoint[], color: string, axis: number, opacity = .12): LineSeriesOption[] {
  if (!data.some(([, minimum, maximum]) => minimum !== null && maximum !== null)) return [];
  const common: LineSeriesOption = { type: "line", xAxisIndex: axis, yAxisIndex: axis, showSymbol: false,
    stack: `history-band:${id}`, stackStrategy: "all", smooth: false, connectNulls: false, silent: true,
    lineStyle: { opacity: 0 }, animation: false, emphasis: { disabled: true }, tooltip: { show: false }, z: 1 };
  return [
    { ...common, id: `history-band:${id}:lower`, data: data.map(([time, minimum]) => [time, minimum]) },
    { ...common, id: `history-band:${id}:width`, areaStyle: { color, opacity },
      data: data.map(([time, minimum, maximum]) => [time, minimum === null || maximum === null ? null : maximum - minimum]) },
  ];
}

export const historyBandSeries = (id: string, data: HistoryChartPoint[], color: string, axis: number): LineSeriesOption[] =>
  bandSeries(id, data.map(point => [point.value[0], point.summary?.minimum ?? null, point.summary?.maximum ?? null]), color, axis);
