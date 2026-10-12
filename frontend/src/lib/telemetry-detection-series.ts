import type { LineSeriesOption } from "echarts/charts";
import type { SecondaryChartSeries } from "@/lib/telemetry-detectors";
import { buildThresholdMarkArea } from "@/lib/telemetry-thresholds";

export const buildDetectionSeriesOption = (
  series: SecondaryChartSeries,
  paneIndex: number,
  domain: readonly [number, number] | undefined,
  colors: { primary: string; alarmFill?: string; alarmBoundary?: string },
  formatTime: (timeMs: number) => string,
  formatValue: (value: number) => string,
): LineSeriesOption => {
  const { bounds } = series;
  const markArea = buildThresholdMarkArea(
    series.thresholdRegions,
    bounds,
    domain,
    colors.alarmFill ?? "rgba(220, 38, 38, 0.12)",
  );
  return {
    id: series.id,
    name: series.name,
    type: "line",
    xAxisIndex: paneIndex,
    yAxisIndex: paneIndex,
    data: series.data,
    smooth: false,
    step: false,
    showSymbol: true,
    symbolSize: 3,
    connectNulls: false,
    lineStyle: { color: colors.primary, width: 2.25, type: "solid" },
    itemStyle: { color: colors.primary },
    emphasis: { disabled: true },
    animation: false,
    markArea,
    markLine: {
      silent: true,
      symbol: ["none", "none"],
      label: { show: false },
      lineStyle: { color: colors.alarmBoundary ?? "#dc2626", width: 1, type: "dashed" },
      data: series.thresholdRegions.flatMap(({ startMs, endMs, threshold }) => {
        const start = Math.max(startMs, domain?.[0] ?? startMs);
        const end = Math.min(endMs, domain?.[1] ?? endMs);
        return end > start ? [[{ coord: [start, threshold] }, { coord: [end, threshold] }]] : [];
      }),
    },
    markPoint: {
      symbol: "triangle",
      symbolSize: 9,
      label: { show: false },
      data: series.overflow.map(({ observation, boundary }) => ({
        name: "Evidence outside plotted range",
        coord: [observation.timeMs, boundary === "upper" ? bounds.maximum : bounds.minimum],
        symbolRotate: boundary === "upper" ? 0 : 180,
        symbolOffset: [0, boundary === "upper" ? 5 : -5],
        itemStyle: { color: colors.alarmBoundary ?? "#dc2626" },
        tooltip: {
          formatter: () => [
            series.name,
            `Time: ${formatTime(observation.timeMs)}`,
            boundary === "upper" ? "Beyond numeric range" : "Evidence is below the logarithmic plotting range",
            observation.value !== null ? `Value: ${formatValue(observation.value)}` : observation.logValue === null ? (boundary === "upper" ? "Value: ∞" : "Value unavailable") : `Log evidence: ${formatValue(observation.logValue)}`,
            `Alarm threshold: ${observation.threshold !== null ? formatValue(observation.threshold) : "unavailable"}`,
            `Alarm: ${observation.alarmActive ? "active" : "inactive"}`,
          ].join("\n"),
        },
      })),
    },
  };
};
