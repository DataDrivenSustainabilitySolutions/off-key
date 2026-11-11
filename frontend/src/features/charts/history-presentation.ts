import type { LineSeriesOption } from "echarts/charts";
import type { HistoryPoint, HistoryPreference, TelemetryHistory } from "@/types/telemetry-history";
import { epochMilliseconds, isoTimestamp } from "@/lib/timestamps";
import { getPauseLimit, type TimeValue } from "./telemetry-data";

export const DEFAULT_HISTORY_PREFERENCE: HistoryPreference = { mode: "auto" };
const INTERVALS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 15000,
  30000, 60000, 120000, 300000, 600000, 900000, 1800000, 3600000, 7200000, 21600000, 43200000, 86400000];

export const intervalLabel = (ms: number): string => ms < 1000 ? `${ms}ms`
  : ms < 60000 ? `${ms / 1000}s` : ms < 3600000 ? `${ms / 60000}m`
  : ms < 86400000 ? `${ms / 3600000}h` : `${ms / 86400000}d`;

/** Only call with original readings, never the historical min/max overview. */
export function presentHistory(data: TimeValue[], preference: HistoryPreference, buckets: number,
  range?: readonly [number, number]): TelemetryHistory {
  const visible = range ? data.filter(([time]) => time >= range[0] && time <= range[1]) : data;
  const first = visible[0]?.[0], last = visible[visible.length - 1]?.[0];
  const history: TelemetryHistory = { representation: "raw", points: visible.map(([time, value]) => ({ timestamp: isoTimestamp(time), value })),
    interval_ms: 0, sample_count: visible.length, extent: first !== undefined && last !== undefined ? [isoTimestamp(first), isoTimestamp(last)] : null, truncated: false };
  if (first === undefined || last === undefined || preference.mode === "raw"
    || (!preference.windowMs && visible.length <= buckets * 2)) return history;
  const target = Math.max(1, ((range?.[1] ?? last) - (range?.[0] ?? first)) / buckets, preference.windowMs ?? 0);
  const interval = INTERVALS.find(value => value >= target) ?? Math.ceil(target / 86400000) * 86400000;
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

export type HistoryChartPoint = { value: [number, number | null]; summary?: HistoryPoint };
export function historyChartData(history: TelemetryHistory): HistoryChartPoint[] {
  const pauseLimit = getPauseLimit(history.points.map(point => epochMilliseconds(point.timestamp)));
  const result: HistoryChartPoint[] = [];
  history.points.forEach((point, index) => {
    const previous = history.points[index - 1];
    const time = epochMilliseconds(point.timestamp);
    if (previous) {
      const previousTime = epochMilliseconds(previous.timestamp);
      const gap = point.start && previous.end
        ? epochMilliseconds(point.start) > epochMilliseconds(previous.end)
        : time - previousTime > pauseLimit;
      if (gap) result.push({ value: [(previousTime + time) / 2, null] });
    }
    result.push({ value: [time, point.value], ...(point.count !== undefined ? { summary: point } : {}) });
  });
  return result;
}

/** Two stacked, silent lines draw the observed range, including negative readings. */
export function historyBandSeries(id: string, data: HistoryChartPoint[], color: string, axis: number): LineSeriesOption[] {
  if (!data.some(point => point.summary)) return [];
  const common: LineSeriesOption = { type: "line", xAxisIndex: axis, yAxisIndex: axis, showSymbol: false,
    stack: `history-band:${id}`, stackStrategy: "all", smooth: false, connectNulls: false, silent: true,
    lineStyle: { opacity: 0 }, animation: false, emphasis: { disabled: true }, tooltip: { show: false }, z: 1 };
  return [
    { ...common, id: `history-band:${id}:lower`, data: data.map(point => [point.value[0], point.summary?.minimum ?? null]) },
    { ...common, id: `history-band:${id}:width`, areaStyle: { color, opacity: .12 },
      data: data.map(point => [point.value[0], point.summary ? point.summary.maximum! - point.summary.minimum! : null]) },
  ];
}
