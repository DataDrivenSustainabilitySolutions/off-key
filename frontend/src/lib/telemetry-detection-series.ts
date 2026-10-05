import type { LineSeriesOption } from "echarts/charts";
import type { SecondaryChartSeries } from "@/lib/telemetry-detectors";
import {
  buildThresholdMarkArea,
  type DetectionValueBounds,
} from "@/lib/telemetry-thresholds";

export const buildDetectionSeriesOption = (
  series: SecondaryChartSeries,
  paneIndex: number,
  bounds: DetectionValueBounds,
  domain: readonly [number, number] | undefined,
  colors: { primary?: string; alarmFill?: string; alarmBoundary?: string },
  formatTime: (timeMs: number) => string,
  formatValue: (value: number) => string,
): LineSeriesOption => {
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
    lineStyle: { color: colors.primary ?? series.color, width: 2.25, type: "solid" },
    itemStyle: { color: colors.primary ?? series.color },
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
      data: series.overflow.map((overflow) => ({
        name: "Evidence outside plotted range",
        coord: [overflow.timeMs, overflow.boundary === "upper" ? bounds.maximum : bounds.minimum],
        symbolRotate: overflow.boundary === "upper" ? 0 : 180,
        symbolOffset: [0, overflow.boundary === "upper" ? 5 : -5],
        itemStyle: { color: colors.alarmBoundary ?? "#dc2626" },
        tooltip: {
          formatter: () => [
            series.name,
            `Time: ${formatTime(overflow.timeMs)}`,
            overflow.boundary === "upper" ? "Beyond numeric range" : "Evidence is below the logarithmic plotting range",
            overflow.value !== null ? `Value: ${formatValue(overflow.value)}` : overflow.logValue === null ? (overflow.boundary === "upper" ? "Value: ∞" : "Value unavailable") : `Log evidence: ${formatValue(overflow.logValue)}`,
            `Alarm threshold: ${overflow.threshold !== null ? formatValue(overflow.threshold) : "unavailable"}`,
            `Alarm: ${overflow.alarmActive ? "active" : "inactive"}`,
          ].join("\n"),
        },
      })),
    },
  };
};
