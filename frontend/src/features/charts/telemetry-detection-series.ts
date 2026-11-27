import type { LineSeriesOption } from "echarts/charts";
import { color as chartColor } from "echarts/core";
import { alarmText, type SecondaryChartSeries } from "./telemetry-detectors";
import { excursions } from "./exceedance";

type DetectionColors = { foreground: string; mutedForeground: string; alarmFill?: string; alarmBoundary?: string };

/**
 * A score is mostly quiet, so its line stays a calm grey: the eye should land only where it
 * passes the threshold (see `buildExcursionSeries`), not on every wiggle below it.
 */
export const buildDetectionSeriesOption = (
  series: SecondaryChartSeries,
  paneIndex: number,
  colors: DetectionColors,
  formatTime: (timeMs: number) => string,
  formatValue: (value: number) => string,
): LineSeriesOption => {
  const { bounds } = series;
  const ink = chartColor.modifyAlpha(colors.mutedForeground, 0.85) ?? colors.mutedForeground;
  return {
    id: series.id,
    name: series.name,
    type: "line",
    xAxisIndex: paneIndex,
    yAxisIndex: paneIndex,
    data: series.data,
    smooth: false,
    step: false,
    showSymbol: false,
    symbol: "none",
    connectNulls: false,
    lineStyle: { color: ink, width: 1.5, join: "round", cap: "round" },
    itemStyle: { color: ink },
    emphasis: { disabled: true },
    animation: false,
    z: 3,
    markPoint: {
      symbol: "triangle",
      symbolSize: 9,
      label: { show: false },
      data: series.overflow.map(({ observation, boundary }) => ({
        name: "Evidence outside plotted range",
        coord: [observation.timeMs, boundary === "upper" ? bounds.maximum : bounds.minimum],
        symbolRotate: boundary === "upper" ? 0 : 180,
        symbolOffset: [0, boundary === "upper" ? 5 : -5],
        itemStyle: { color: observation.alarmActive ? colors.alarmBoundary ?? "#dc2626" : colors.foreground },
        tooltip: {
          formatter: () => [
            series.name,
            `Time: ${formatTime(observation.timeMs)}`,
            boundary === "upper" ? observation.value === null ? "Beyond numeric range" : "Above the plotted range" : "Evidence is below the logarithmic plotting range",
            observation.value !== null ? `Value: ${formatValue(observation.value)}` : observation.logValue === null ? (boundary === "upper" ? "Value: ∞" : "Value unavailable") : `Log evidence: ${formatValue(observation.logValue)}`,
            `Alarm threshold: ${observation.threshold !== null ? formatValue(observation.threshold) : "unavailable"}`,
            `Alarm: ${alarmText(observation)}`,
          ].join("\n"),
        },
      })),
    },
  };
};

/**
 * The threshold as one quiet rule. Measured against its own threshold a score's limit is the
 * straight line at 1; a fixed threshold keeps its own value, stepped where it was changed.
 */
export const buildThresholdSeriesOption = (
  series: SecondaryChartSeries,
  paneIndex: number,
  color: string,
): LineSeriesOption => {
  const style = { color, width: 1, type: [4, 3] as number[], opacity: 0.9 };
  const common = { xAxisIndex: paneIndex, yAxisIndex: paneIndex, emphasis: { disabled: true }, animation: false, silent: true,
    tooltip: { show: false } } as const;
  if (series.relative) {
    return { ...common, id: `threshold:${series.id}`, name: "Alarm threshold", type: "line", data: [], z: 2,
      markLine: { silent: true, animation: false, symbol: ["none", "none"], lineStyle: style,
        label: { show: false }, data: [{ yAxis: 1 }] } };
  }
  return { ...common, id: `threshold:${series.id}`, name: "Alarm threshold", type: "line", z: 2,
    data: series.data.map(point => [point.value[0], point.observation?.threshold ?? null]),
    step: "end", showSymbol: false, connectNulls: false, lineStyle: style, itemStyle: { color } };
};

/**
 * What passed the threshold, drawn over the score. A crossing the monitor did not alarm on is
 * expected behaviour (its rule may need several results in a row, a gate or a warm-up), so it
 * only darkens the grey and shades faintly. The alarm is the one saturated mark.
 */
export const buildExcursionSeries = (
  series: SecondaryChartSeries,
  paneIndex: number,
  colors: DetectionColors,
): LineSeriesOption[] => {
  const alarm = colors.alarmBoundary ?? "#dc2626";
  const samples = series.data.map(point => {
    const value = point.value[1], threshold = series.relative ? 1 : point.observation?.threshold ?? null;
    return { time: point.value[0], value, margin: value === null || threshold === null ? null : value - threshold,
      kind: point.observation?.alarmActive || point.observation?.alarmFired ? "alarm" : "quiet" };
  });
  const lines = excursions(samples, ["quiet", "alarm"]);
  const quiet = chartColor.modifyAlpha(colors.foreground, 0.62) ?? colors.foreground;
  return ([
    ["quiet", quiet, 0.1],
    ["alarm", alarm, 0],
  ] as const).flatMap(([kind, color, opacity]) => lines[kind]!.length ? [{
    id: `excursion:${kind}:${series.id}`,
    name: kind === "alarm" ? "Alarm" : "Above threshold",
    type: "line" as const,
    xAxisIndex: paneIndex,
    yAxisIndex: paneIndex,
    data: lines[kind],
    showSymbol: false,
    connectNulls: false,
    lineStyle: { color, width: kind === "alarm" ? 2 : 1.5, join: "round" as const, cap: "round" as const },
    itemStyle: { color },
    ...(series.relative && opacity ? { areaStyle: { origin: 1, color: chartColor.modifyAlpha(color, opacity) ?? color } } : {}),
    emphasis: { disabled: true },
    animation: false,
    silent: true,
    tooltip: { show: false },
    z: 4,
  }] : []);
};
