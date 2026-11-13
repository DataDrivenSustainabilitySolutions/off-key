import type { LineSeriesOption } from "echarts/charts";
import { latestForecast, type ForecastEvidenceSeries } from "./forecast-evidence";
import type { FutureForecastPoint } from "./forecast-future";

export function buildFutureChartSeries(forecast: ForecastEvidenceSeries, pane: number, color: string): LineSeriesOption[] {
  const points = forecast.future ?? [];
  if (!points.length) return [];
  const observed = latestForecast(forecast);
  const origin = points[0]!.originTime;
  const data: Array<{ value: [number, number]; futureForecast?: FutureForecastPoint }> = points.map(point => ({
    value: [point.time, point.expected], futureForecast: point,
  }));
  // Only join to the actual origin used by the model. A later raw sample must
  // not become the apparent origin of an older issued trajectory.
  if (observed?.time === origin && observed.observed !== null) data.unshift({ value: [origin, observed.observed] });
  const trajectory: LineSeriesOption = {
    id: `future:${forecast.id}`, name: `${forecast.name} forecast ahead`, type: "line",
    xAxisIndex: pane, yAxisIndex: pane, data, encode: { x: 0, y: 1 },
    lineStyle: { color, width: 1.8, type: "dashed" }, itemStyle: { color },
    showSymbol: true, symbolSize: 4, connectNulls: false, animation: false, emphasis: { disabled: true }, z: 4,
    // An interval at one calibrated lead is a whisker, not a band implying
    // calibration for all the model's other leads.
    markLine: { silent: true, symbol: ["none", "none"], label: { show: false },
      lineStyle: { color, width: 3, type: "solid", opacity: 0.5 },
      data: [{ xAxis: origin, lineStyle: { width: 1, type: "dotted", opacity: 0.35 } },
        ...points.flatMap(point => point.lower === null || point.upper === null ? [] : [[
          { coord: [point.time, point.lower] }, { coord: [point.time, point.upper] },
        ] as [{ coord: number[] }, { coord: number[] }]]),
      ],
    },
  };
  // Include the interval in axis extents even when historical bands are hidden.
  const bounds: LineSeriesOption[] = (["lower", "upper"] as const).map(bound => ({
    id: `future-bounds:${forecast.id}:${bound}`, type: "line", xAxisIndex: pane, yAxisIndex: pane,
    data: points.map(point => [point.time, point[bound]]), showSymbol: false,
    silent: true, lineStyle: { opacity: 0 }, tooltip: { show: false }, animation: false,
  }));
  return [trajectory, ...bounds];
}

export function formatFutureTooltip(entries: Array<{ seriesName?: string; value?: unknown;
  data?: { futureForecast?: FutureForecastPoint } }>, timestamp: number,
  time: (value: number) => string, number: (value: number) => string, intervalLabel: string): string | undefined {
  const future = entries.filter(entry => entry.data?.futureForecast?.time === timestamp);
  if (!future.length) return undefined;
  const lines = [`Estimated target: ${time(timestamp)}`];
  for (const entry of future) {
    const point = entry.data!.futureForecast!;
    lines.push(entry.seriesName ?? "Forecast ahead",
      `Forecast: ${number(point.expected)} · ${point.lead} ${point.lead === 1 ? "update" : "updates"} ahead`,
      `Issued: ${time(point.issuedAt)}`, `Origin: ${time(point.originTime)}`,
      point.lower === null || point.upper === null ? "No calibrated interval for this lead."
        : `${intervalLabel} at issue: ${number(point.lower)} to ${number(point.upper)}`);
  }
  lines.push("Time estimated from recent cadence.", "Outcome not yet observed.");
  return lines.join("\n");
}
