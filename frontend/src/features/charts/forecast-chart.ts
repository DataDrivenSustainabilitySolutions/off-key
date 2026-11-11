import type { LineSeriesOption } from "echarts/charts";
import type { ForecastEvidenceSeries, ForecastObservation, ForecastValue } from "./forecast-evidence";
import { intervalStatus } from "./forecast-evidence";
import type { DetectionObservation } from "./telemetry-detectors";
import type { ForecastView, FutureForecastPoint } from "./forecast-future";
import { buildFutureChartSeries, formatFutureTooltip } from "./forecast-future-chart";

/** Stack the width on the lower bound, including when the interval crosses zero. */
function intervalSeries(id: string, data: ForecastValue[], pane: number, color: string): LineSeriesOption[] {
  if (!data.some(([, , lower, upper]) => lower !== null && upper !== null)) return [];
  const shared: LineSeriesOption = { type: "line", xAxisIndex: pane, yAxisIndex: pane,
    stack: `forecast-band:${id}`, stackStrategy: "all", showSymbol: false, connectNulls: false,
    silent: true, lineStyle: { opacity: 0 }, emphasis: { disabled: true }, animation: false, tooltip: { show: false } };
  return [
    { ...shared, id: `forecast-band:${id}:lower`, data: data.map(([time, , lower]) => [time, lower]) },
    { ...shared, id: `forecast-band:${id}:width`, areaStyle: { color, opacity: 0.15 },
      data: data.map(([time, , lower, upper]) => [time, lower === null || upper === null ? null : upper - lower]) },
  ];
}

export function buildForecastChartSeries(forecast: ForecastEvidenceSeries, pane: number, residualPane: number,
  color: string, alarmColor: string, view: ForecastView = "overlay"): LineSeriesOption[] {
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
      lineStyle: { color, width: 1.8, type: "dashed" }, itemStyle: { color }, z: 4 },
  ];
  const residualSeries: LineSeriesOption[] = [
    ...intervalSeries(`residual:${forecast.id}`, residuals.map(point => point.value), residualPane, color),
    { ...common, id: `residual:${forecast.id}`, name: `${forecast.name} residual`,
      xAxisIndex: residualPane, yAxisIndex: residualPane, data: residuals,
      lineStyle: { color, width: 1.5 }, itemStyle: { color },
      markLine: { silent: true, symbol: ["none", "none"], label: { show: false },
        lineStyle: { color, type: "dotted", opacity: 0.6 }, data: [{ yAxis: 0 }] },
      markPoint: { symbol: "circle", symbolSize: 6, label: { show: false }, data: residuals.flatMap(point =>
        point.forecastObservation && intervalStatus(point.forecastObservation) === "Outside interval"
          ? [{ name: "Outside calibrated interval", coord: [point.value[0], point.value[1]!], itemStyle: { color: alarmColor } }] : []) } },
  ];
  return [
    ...(view === "overlay" ? history : []),
    ...(view !== "data" ? buildFutureChartSeries(forecast, pane, color) : []),
    ...(residualPane >= 0 ? residualSeries : []),
  ];
}

type TooltipEntry = { seriesId?: string; seriesName?: string; value?: unknown;
  data?: { forecastObservation?: ForecastObservation; observation?: DetectionObservation; futureForecast?: FutureForecastPoint } };

/** Never show a neighbouring forecast as if it evaluated the hovered sample. */
export function formatForecastTooltip(params: unknown, time: (value: number) => string,
  number: (value: number) => string, intervalLabel: string, showMissing = true): string | undefined {
  const entries = (Array.isArray(params) ? params : [params]).filter((entry): entry is TooltipEntry => !!entry && typeof entry === "object");
  const anchor = entries.find(entry => Array.isArray(entry.value));
  if (!Array.isArray(anchor?.value)) return undefined;
  const timestamp = Number(anchor.value[0]);
  const future = formatFutureTooltip(entries, timestamp, time, number, intervalLabel);
  if (future) return future;
  const points = entries.filter(entry => entry.data?.forecastObservation?.time === timestamp);
  if (!points.length) return showMissing && (anchor.seriesId?.startsWith("reading:") || anchor.seriesId?.startsWith("pending-reading:"))
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
    if (point.observed !== null) lines.push(`Residual: ${number(point.observed - point.expected)} · ${intervalStatus(point)}`);
    lines.push(`Service alarm: ${point.alarm ? "active" : "inactive"}`);
  }
  for (const entry of entries) {
    const result = entry.data?.observation;
    if (!result || !evaluationTimes.has(result.timeMs)) continue;
    lines.push(`${entry.seriesName}: ${result.value === null ? result.isInfinite ? "∞" : "unavailable" : number(result.value)}`);
    lines.push(`Score threshold: ${result.threshold === null ? "unavailable" : number(result.threshold)}`);
  }
  return lines.join("\n");
}
