import type { LineSeriesOption } from "echarts/charts";
import type { ForecastEvidenceSeries, ForecastObservation, ForecastValue } from "./forecast-evidence";
import { intervalStatus, isOutside } from "./forecast-evidence";
import type { DetectionObservation } from "./telemetry-detectors";
import { excursions } from "./exceedance";
import type { FutureForecastPoint } from "./forecast-future";
import { buildFutureChartSeries, formatFutureTooltip } from "./forecast-future-chart";

/** Stack the width on the lower bound, including when the interval crosses zero. */
function intervalSeries(id: string, data: ForecastValue[], pane: number, color: string): LineSeriesOption[] {
  if (!data.some(([, , lower, upper]) => lower !== null && upper !== null)) return [];
  const shared: LineSeriesOption = { type: "line", xAxisIndex: pane, yAxisIndex: pane,
    stack: `forecast-band:${id}`, stackStrategy: "all", showSymbol: false, connectNulls: false,
    silent: true, lineStyle: { opacity: 0 }, emphasis: { disabled: true }, animation: false, tooltip: { show: false } };
  return [
    { ...shared, id: `forecast-band:${id}:lower`, data: data.map(([time, , lower]) => [time, lower]) },
    { ...shared, id: `forecast-band:${id}:width`, areaStyle: { color, opacity: 0.22 },
      data: data.map(([time, , lower, upper]) => [time, lower === null || upper === null ? null : upper - lower]) },
  ];
}

type Checked = { time: number; value: number | null; lower: number | null; upper: number | null; alarm?: boolean };

/** How far the observed value lay past the interval, filled between the two: its size is the
 * quantity. A stray value outside, which a 90 % interval expects one time in ten, is a sliver;
 * a sustained departure is a wedge you see at once. Inside an alarm the band already says it.
 * The fill tapers to the interval edge at the neighbouring values, so it has no hard ends. */
function outsideArea(id: string, pane: number, color: string, points: readonly Checked[]): LineSeriesOption[] {
  const side = ({ value, lower, upper, alarm }: Checked) => value === null || lower === null || upper === null || alarm ? undefined
    : value > upper ? "upper" as const : value < lower ? "lower" as const : undefined;
  const sides = points.map(side);
  // A departure that runs into an alarm belongs to it: the alarm band tells that story, so its run gets no fill.
  for (let index = 0; index < sides.length; index++) {
    if (!sides[index]) continue;
    let end = index;
    while (sides[end + 1]) end++;
    if (points[index - 1]?.alarm || points[end + 1]?.alarm) sides.fill(undefined, index, end + 1);
    index = end;
  }
  const base: Array<[number, number | null]> = [], width: Array<[number, number | null]> = [];
  points.forEach((point, index) => {
    const own = sides[index], near = own ?? sides[index - 1] ?? sides[index + 1];
    const edge = near === "upper" ? point.upper : near === "lower" ? point.lower : null;
    if (!near || edge === null || point.value === null) { base.push([point.time, null]); width.push([point.time, null]); return; }
    const reach = own ? Math.abs(point.value - edge) : 0;
    base.push([point.time, own === "lower" ? point.value : edge]);
    width.push([point.time, reach]);
  });
  if (!sides.some(Boolean)) return [];
  const shared: LineSeriesOption = { type: "line", xAxisIndex: pane, yAxisIndex: pane, stack: `outside:${id}`, stackStrategy: "all",
    showSymbol: false, connectNulls: false, silent: true, lineStyle: { opacity: 0 }, emphasis: { disabled: true }, animation: false,
    tooltip: { show: false }, z: 2 };
  // The stretch of the observed line past the edge, in the same colour, so even a thin departure is found.
  const { outside } = excursions(points.map((point, index) => {
    const edge = sides[index] === "upper" ? point.upper : sides[index] === "lower" ? point.lower : null;
    return { time: point.time, value: point.value,
      margin: point.value === null ? null : edge === null ? -1 : Math.abs(point.value - edge) };
  }), ["outside"]);
  return [
    { ...shared, id: `outside:${id}:base`, data: base },
    { ...shared, id: `outside:${id}:reach`, name: "Outside interval", data: width, areaStyle: { color, opacity: 0.3 } },
    { id: `outside:${id}:line`, type: "line", xAxisIndex: pane, yAxisIndex: pane, data: outside, showSymbol: false, connectNulls: false,
      silent: true, tooltip: { show: false }, emphasis: { disabled: true }, animation: false, z: 5,
      lineStyle: { color, width: 1.75, join: "round", cap: "round" } },
  ];
}

export function buildForecastChartSeries(forecast: ForecastEvidenceSeries, pane: number, residualPane: number,
  color: string, outsideColor: string, ink = color): LineSeriesOption[] {
  const common: LineSeriesOption = { type: "line", showSymbol: forecast.data.length === 1, symbolSize: 5,
    connectNulls: false, encode: { x: 0, y: 1 }, emphasis: { disabled: true }, animation: false };
  const residuals = forecast.data.map(({ value: [time], forecastObservation: point }) => ({
    value: [time, point?.observed == null ? null : point.observed - point.expected,
      point?.lower == null ? null : point.lower - point.expected,
      point?.upper == null ? null : point.upper - point.expected] as ForecastValue,
    forecastObservation: point,
  }));
  const history: LineSeriesOption[] = [
    ...intervalSeries(forecast.id, forecast.data.map(point => point.value), pane, color),
    { ...common, id: `forecast:${forecast.id}`, name: `${forecast.name} forecast`,
      xAxisIndex: pane, yAxisIndex: pane, data: forecast.data,
      lineStyle: { color, width: 1.6, type: "dashed" }, itemStyle: { color }, z: 4 },
    ...outsideArea(forecast.id, pane, outsideColor, forecast.data.map(({ value: [time], forecastObservation: point }) =>
      ({ time, value: point?.observed ?? null, lower: point?.lower ?? null, upper: point?.upper ?? null, alarm: point?.alarm }))),
  ];
  const residualSeries: LineSeriesOption[] = [
    ...intervalSeries(`residual:${forecast.id}`, residuals.map(point => point.value), residualPane, color),
    { ...common, id: `residual:${forecast.id}`, name: `${forecast.name} residual`,
      xAxisIndex: residualPane, yAxisIndex: residualPane, data: residuals,
      lineStyle: { color, width: 1.5 }, itemStyle: { color },
      markLine: { silent: true, symbol: ["none", "none"], label: { show: false },
        lineStyle: { color, type: "dotted", opacity: 0.6 }, data: [{ yAxis: 0 }] } },
    ...outsideArea(`residual:${forecast.id}`, residualPane, outsideColor, residuals.map(({ value: [time, residual, lower, upper], forecastObservation: point }) =>
      ({ time, value: residual, lower, upper, alarm: point?.alarm }))),
  ];
  return [
    ...history,
    ...buildFutureChartSeries(forecast, pane, color, ink),
    ...(residualPane >= 0 ? residualSeries : []),
  ];
}

type TooltipEntry = { seriesId?: string; seriesName?: string; value?: unknown;
  data?: { forecastObservation?: ForecastObservation; observation?: DetectionObservation; futureForecast?: FutureForecastPoint;
    summary?: unknown } };

/** Never show a neighbouring forecast as if it evaluated the hovered sample. */
export function formatForecastTooltip(params: unknown, time: (value: number) => string,
  number: (value: number) => string, intervalLabel: string): string | undefined {
  const entries = (Array.isArray(params) ? params : [params]).filter((entry): entry is TooltipEntry => !!entry && typeof entry === "object");
  const anchor = entries.find(entry => Array.isArray(entry.value));
  if (!Array.isArray(anchor?.value)) return undefined;
  const timestamp = Number(anchor.value[0]);
  const future = formatFutureTooltip(entries, timestamp, time, number, intervalLabel);
  if (future) return future;
  const points = entries.filter(entry => entry.data?.forecastObservation?.time === timestamp);
  // An interval mean is not an input sample, so its own tooltip names the interval, range and count.
  if (!points.length && entries.some(entry => entry.data?.summary)) return undefined;
  if (!points.length) return (anchor.seriesId?.startsWith("reading:") || anchor.seriesId?.startsWith("pending-reading:"))
    ? [time(timestamp), `${anchor.seriesName}: ${number(Number(anchor.value[1]))}`, "No evaluated forecast for this input sample."].join("\n")
    : undefined;
  const lines = [time(timestamp)];
  const seen = new Set<string>();
  const evaluationTimes = new Set<number>();
  for (const entry of points) {
    const point = entry.data!.forecastObservation!;
    const id = entry.seriesId?.replace(/^(forecast|residual):/, "") ?? entry.seriesName ?? "";
    if (seen.has(id)) continue;
    seen.add(id);
    evaluationTimes.add(point.evaluationTime);
    lines.push(entry.seriesName?.replace(/ (forecast|residual)$/, "") ?? "Forecast");
    lines.push(`Observed: ${point.observed === null ? "unavailable" : number(point.observed)} · Forecast: ${number(point.expected)}`);
    lines.push(point.lower === null || point.upper === null ? "Interval unavailable"
      : `${intervalLabel}: ${number(point.lower)} to ${number(point.upper)}`);
    if (point.observed !== null) lines.push(`Residual: ${number(point.observed - point.expected)} · ${intervalStatus(point)}${isOutside(point) ? " (not an anomaly by itself)" : ""}`);
    lines.push(`Monitor alarm: ${point.alarm ? "active" : "inactive"}`);
  }
  for (const entry of entries) {
    const result = entry.data?.observation;
    if (!result || !evaluationTimes.has(result.timeMs)) continue;
    lines.push(`${entry.seriesName}: ${result.value === null ? result.isInfinite ? "∞" : "unavailable" : number(result.value)}`);
    lines.push(`Score threshold: ${result.threshold === null ? "unavailable" : number(result.threshold)}`);
  }
  return lines.join("\n");
}
