import type { TelemetryChartOption, ChartThemeColors } from "../charts/telemetry-chart";
import { timeAxisLabelFormatter } from "../charts/time-axis";
import type { ChartPoint } from "./model";

type ChartSeries = { id: string; name: string; unit: string | null; points: ChartPoint[] };
type ChartLabel = { id: string; start: number; end: number; note: string };
type ChartAlarms = { id: string; name: string; times: number[] };

export type DojoChartData = {
  series: ChartSeries[];
  labels: ChartLabel[];
  /** One row of alarm marks per run, below the values. */
  alarms?: ChartAlarms[];
};

type Input = DojoChartData & {
  colors: ChartThemeColors;
  timeZone: string;
  locale?: string;
  viewport?: [number, number];
};

const ALARM_ROW = 22;
const scaleKey = (item: ChartSeries) => item.unit ? `unit:${item.unit}` : `series:${item.id}`;
export const chartScaleKeys = (series: ChartSeries[]) => [...new Set(series.map(scaleKey))];

function labelAreas(labels: ChartLabel[], colors: ChartThemeColors) {
  return {
    silent: true,
    itemStyle: { color: colors.alarmFill, borderColor: colors.alarmBoundary, borderWidth: 0 },
    data: labels.map(label => [{ xAxis: label.start, name: label.note }, { xAxis: label.end }]),
    label: { show: false },
  };
}

export function dojoChartExtent({ series, labels, alarms = [] }: DojoChartData): [number, number] | undefined {
  let low = Infinity, high = -Infinity;
  const add = (time: number) => { if (time < low) low = time; if (time > high) high = time; };
  for (const item of series) if (item.points.length) { add(item.points[0]![0]); add(item.points[item.points.length - 1]![0]); }
  for (const label of labels) { add(label.start); add(label.end); }
  for (const item of alarms) for (const time of item.times) add(time);
  return low <= high ? [low, high] : undefined;
}

/** Values of a dataset with its labels shaded, and optionally each run's alarms.
 *
 * Two different scales appear on separate axes. Series with a known matching
 * unit share a scale. An overview with more than two scales uses one shared axis.
 * The legend names the units and axes. Alarm rows share the time axis, so a
 * mark sits under the value it belongs to.
 */
export function datasetChartOption({ series, labels, alarms = [], colors, timeZone, locale, viewport }: Input): TelemetryChartOption {
  const range = dojoChartExtent({ series, labels, alarms });
  const span = range ? range[1] - range[0] : 0;
  const palette = colors.seriesPalette ?? [colors.primary];
  const scales = chartScaleKeys(series);
  const twoAxes = scales.length === 2;
  const longest = Math.max(0, ...alarms.map(item => item.name.length));
  const left = alarms.length ? Math.min(134, Math.max(56, 16 + longest * 7)) : 56;
  const right = twoAxes ? 56 : 24;
  const alarmHeight = alarms.length ? alarms.length * ALARM_ROW + 18 : 0;
  const labelStyle = { color: colors.mutedForeground, fontSize: 12 };
  const axisLabel = { ...labelStyle, formatter: timeAxisLabelFormatter(timeZone, locale, span), hideOverlap: true,
    rich: { day: { fontWeight: 600 } } };
  const bounds = range ? { min: range[0], max: range[1] } : {};
  const timeAxis = (id: string, gridIndex: number, labelled: boolean) => ({ id, type: "time" as const, gridIndex, ...bounds,
    axisLabel: labelled ? axisLabel : { show: false }, axisLine: { lineStyle: { color: colors.border } } });
  const xAxis = [timeAxis("time", 0, !alarms.length)];
  const valueAxis = (index: number) => ({ id: `value:${index}`, type: "value", gridIndex: 0, scale: true,
    position: index === 1 ? "right" : "left", axisLabel: labelStyle,
    splitLine: { show: index === 0, lineStyle: { color: colors.border } } });
  const yAxis: object[] = [valueAxis(0), ...(twoAxes ? [valueAxis(1)] : [])];
  if (alarms.length) {
    xAxis.push(timeAxis("alarm-time", 1, true));
    yAxis.push({ id: "alarm-run", type: "category", gridIndex: 1, inverse: true, data: alarms.map(item => item.name),
      axisLabel: { ...labelStyle, width: left - 14, overflow: "truncate" },
      axisTick: { show: false }, axisLine: { show: false }, splitLine: { show: false } });
  }
  const lines = series.map((item, index) => ({
    id: `series:${item.id}`,
    type: "line" as const,
    name: `${item.name}${item.unit ? ` (${item.unit})` : ""}${twoAxes ? scaleKey(item) === scales[0] ? " · left" : " · right" : ""}`,
    data: item.points,
    xAxisIndex: 0,
    yAxisIndex: twoAxes && scaleKey(item) === scales[1] ? 1 : 0,
    showSymbol: false,
    sampling: "lttb" as const,
    large: true,
    lineStyle: { width: 1.2 },
    color: palette[index % palette.length],
    ...(index === 0 ? { markArea: labelAreas(labels, colors) } : {}),
  }));
  const alarmAxis = yAxis.length - 1;
  const marks = alarms.map((item, index) => ({
    id: `alarms:${item.id}`,
    type: "scatter" as const,
    name: `Alarms · ${item.name}`,
    data: item.times.map(time => [time, item.name]),
    xAxisIndex: 1,
    yAxisIndex: alarmAxis,
    symbol: "rect",
    symbolSize: [2, 14],
    large: true,
    color: palette[(series.length + index) % palette.length],
    ...(index === 0 ? { markArea: labelAreas(labels, colors) } : {}),
  }));
  const grid: object[] = [{ id: "values", left, right, top: 36, bottom: 64 + alarmHeight }];
  if (alarms.length) grid.push({ id: "alarms", left, right, bottom: 64, height: alarms.length * ALARM_ROW });
  const zoom = { xAxisIndex: alarms.length ? [0, 1] : [0], filterMode: "none",
    ...(viewport ? { startValue: viewport[0], endValue: viewport[1] } : { start: 0, end: 100 }) };
  return {
    animation: false,
    grid,
    legend: { type: "scroll", top: 0, left: 4, right: 4, data: lines.map(line => line.name),
      textStyle: labelStyle, pageIconColor: colors.foreground, pageIconInactiveColor: colors.border, pageTextStyle: labelStyle },
    tooltip: { trigger: "axis", axisPointer: { type: "line" },
      backgroundColor: colors.popover, borderColor: colors.border, textStyle: { color: colors.popoverForeground } },
    xAxis,
    yAxis,
    dataZoom: [
      { ...zoom, type: "inside", zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false },
      { ...zoom, type: "slider", bottom: 12, height: 22, left, right },
    ],
    series: [...lines, ...marks],
  } as TelemetryChartOption;
}
