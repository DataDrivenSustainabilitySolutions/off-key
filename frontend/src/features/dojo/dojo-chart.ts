import { color as chartColor } from "echarts/core";
import type { TelemetryChartOption, ChartThemeColors } from "../charts/telemetry-chart";
import { timeAxisLabelFormatter } from "../charts/time-axis";
import { LOCALE } from "@/lib/locale";
import type { ChartPoint } from "./model";

type ChartSeries = { id: string; name: string; unit: string | null; points: ChartPoint[] };
type ChartLabel = { id: string; start: number; end: number; note: string };
type ChartAlarms = { id: string; name: string; times: number[] };

type Input = {
  series: ChartSeries[];
  labels: ChartLabel[];
  /** One row of alarm marks per run, below the values. */
  alarms?: ChartAlarms[];
  /** A range about to become a label, outlined over the values. */
  draft?: { start: number; end: number } | null;
  /** Lets a drag across the values pick a range (see EChart's rangeSelect). */
  selectable?: boolean;
  colors: ChartThemeColors;
  timeZone: string;
};

const ALARM_ROW = 22;
const TOOLTIP_NUMBER = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 3 });
const ALARM_BAR = 12;

/** A label is what a person marked, not what a design alarmed on, so it is a neutral band: red is kept for alarms. */
function labelAreas(labels: ChartLabel[], colors: ChartThemeColors, draft: Input["draft"] = null) {
  const shade = (alpha: number) => chartColor.modifyAlpha(colors.foreground, alpha) ?? colors.foreground;
  return {
    silent: true,
    itemStyle: { color: shade(0.12), borderWidth: 0 },
    data: [...labels.map(label => [{ xAxis: label.start, name: label.note }, { xAxis: label.end }]),
      ...draft ? [[{ xAxis: draft.start, itemStyle: { color: shade(0.05), borderColor: shade(0.55), borderWidth: 1,
        borderType: "dashed" } }, { xAxis: draft.end }]] : []],
    label: { show: false },
  };
}

function extent(series: ChartSeries[], labels: ChartLabel[], alarms: ChartAlarms[]): [number, number] | undefined {
  let low = Infinity, high = -Infinity;
  const add = (time: number) => { if (time < low) low = time; if (time > high) high = time; };
  for (const item of series) if (item.points.length) { add(item.points[0]![0]); add(item.points[item.points.length - 1]![0]); }
  for (const label of labels) { add(label.start); add(label.end); }
  for (const item of alarms) for (const time of item.times) add(time);
  return low <= high ? [low, high] : undefined;
}

const median = (values: number[]) => values.length ? [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)]! : undefined;
const gaps = (times: readonly number[]) => times.slice(1).map((time, index) => time - times[index]!).filter(gap => gap > 0);

/** Alarms one after the other at the data's own cadence are one episode, drawn as one bar from its first to its last alarm,
 * half a step wider on each side so a single alarm still has a width. A break in the line separates episodes. */
export function alarmEpisodes(times: readonly number[], cadence?: number): Array<[number, number]> {
  const sorted = [...times].sort((a, b) => a - b);
  const step = cadence ?? median(gaps(sorted)) ?? 0;
  const episodes: Array<[number, number]> = [];
  for (const time of sorted) {
    const last = episodes[episodes.length - 1];
    if (last && time - last[1] <= step * 1.5) last[1] = time;
    else episodes.push([time, time]);
  }
  return episodes.map(([start, end]) => [start - step / 2, end + step / 2]);
}

/** Values of a dataset with its labels shaded, and optionally each run's alarms.
 *
 * Series share an axis per unit: the first unit on the left, the second on the
 * right, any further ones on the left. The legend names each series' unit. Alarm rows share the time axis, so a
 * mark sits under the value it belongs to.
 */
export function datasetChartOption({ series, labels, alarms = [], draft = null, selectable = false, colors, timeZone }: Input): TelemetryChartOption {
  const range = extent(series, labels, alarms);
  const band = (alpha: number) => chartColor.modifyAlpha(colors.foreground, alpha) ?? colors.foreground;
  const span = range ? range[1] - range[0] : 0;
  const palette = colors.seriesPalette ?? [colors.primary];
  const units = [...new Set(series.map(item => item.unit ?? ""))];
  const twoAxes = units.length > 1;
  const longest = Math.max(0, ...alarms.map(item => item.name.length));
  const left = alarms.length ? Math.min(180, Math.max(56, 16 + longest * 7)) : 56;
  const right = twoAxes ? 56 : 24;
  const alarmHeight = alarms.length ? alarms.length * ALARM_ROW + 18 : 0;
  const axisLabel = { formatter: timeAxisLabelFormatter(timeZone, span), hideOverlap: true,
    rich: { day: { fontWeight: 600 } } };
  const bounds = range ? { min: range[0], max: range[1] } : {};
  const timeAxis = (id: string, gridIndex: number, labelled: boolean) => ({ id, type: "time" as const, gridIndex, ...bounds,
    axisLabel: labelled ? axisLabel : { show: false }, axisLine: { lineStyle: { color: colors.border } } });
  const xAxis = [timeAxis("time", 0, !alarms.length)];
  const valueAxis = (index: number) => ({ id: `value:${index}`, type: "value", gridIndex: 0, scale: true,
    position: index === 1 ? "right" : "left",
    splitLine: { show: index === 0, lineStyle: { color: colors.border } } });
  const yAxis: object[] = [valueAxis(0), ...(twoAxes ? [valueAxis(1)] : [])];
  if (alarms.length) {
    xAxis.push(timeAxis("alarm-time", 1, true));
    yAxis.push({ id: "alarm-run", type: "category", gridIndex: 1, inverse: true, data: alarms.map(item => item.name),
      axisTick: { show: false }, axisLine: { show: false }, splitLine: { show: false } });
  }
  const lines = series.map((item, index) => ({
    id: `series:${item.id}`,
    type: "line" as const,
    name: item.unit ? `${item.name} (${item.unit})` : item.name,
    data: item.points,
    xAxisIndex: 0,
    yAxisIndex: units.indexOf(item.unit ?? "") === 1 ? 1 : 0,
    showSymbol: false,
    sampling: "lttb" as const,
    large: true,
    lineStyle: { width: 1.2 },
    color: palette[index % palette.length],
    ...(index === 0 ? { markArea: labelAreas(labels, colors, draft) } : {}),
  }));
  const alarmAxis = yAxis.length - 1;
  const cadence = median(series.flatMap(item => gaps(item.points.map(point => point[0]))));
  const alarm = colors.alarmBoundary;
  // Every alarm of a run in the alarm colour: the row's name says which run, so colour need not.
  const marks = alarms.map((item, index) => ({
    id: `alarms:${item.id}`,
    type: "line" as const,
    name: `Alarms · ${item.name}`,
    data: alarmEpisodes(item.times, cadence).flatMap(([start, end]) => [[start, item.name], [end, item.name], [end, null]]),
    xAxisIndex: 1,
    yAxisIndex: alarmAxis,
    connectNulls: false,
    symbol: "rect",
    symbolSize: [2, ALARM_BAR],
    showSymbol: true,
    lineStyle: { width: ALARM_BAR, cap: "butt" as const, color: alarm },
    itemStyle: { color: alarm },
    emphasis: { disabled: true },
    tooltip: { show: false },
    ...(index === 0 ? { markArea: labelAreas(labels, colors) } : {}),
  }));
  const grid: object[] = [{ id: "values", left, right, top: 36, bottom: 64 + alarmHeight }];
  if (alarms.length) grid.push({ id: "alarms", left, right, bottom: 64, height: alarms.length * ALARM_ROW });
  return {
    animation: false,
    grid,
    legend: { type: "scroll", top: 0, left, right, textStyle: { color: colors.mutedForeground },
      data: lines.map(line => line.name) },
    tooltip: { trigger: "axis", axisPointer: { type: "line" },
      valueFormatter: (value: unknown) => typeof value === "number" ? TOOLTIP_NUMBER.format(value) : String(value ?? "–") },
    xAxis,
    yAxis,
    dataZoom: [
      { type: "inside", xAxisIndex: alarms.length ? [0, 1] : [0], filterMode: "none" },
      { type: "slider", xAxisIndex: alarms.length ? [0, 1] : [0], filterMode: "none", bottom: 12, height: 22, left, right },
    ],
    ...(selectable ? { toolbox: { show: false }, brush: { toolbox: [], xAxisIndex: 0, brushType: "lineX", brushMode: "single", transformable: false,
      throttleType: "debounce", throttleDelay: 0, outOfBrush: { colorAlpha: 1 },
      brushStyle: { color: band(0.12), borderColor: band(0.4), borderWidth: 1 } } } : {}),
    series: [...lines, ...marks],
  } as TelemetryChartOption;
}
