import type { LineSeriesOption, ScatterSeriesOption } from "echarts/charts";
import type {
  AriaComponentOption,
  AxisPointerComponentOption,
  DataZoomComponentOption,
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
} from "echarts/components";
import { color as chartColor, type ComposeOption } from "echarts/core";
import { buildDetectionSeriesOption, buildThresholdSeriesOption } from "./telemetry-detection-series";
import { formatMonitoringObservationTooltip } from "./monitoring-tooltip";

import type { AnomalyMarker } from "@/lib/anomaly-utils";
import type { TimeValue } from "./telemetry-data";
import type { MonitoringChartReading, TelemetryChartSeries } from "./types";
import {
  buildSelectedDetectorSeries,
  type TelemetryChartDetector,
  type SecondaryChartSeries,
  type SelectedDetectorIds,
} from "./telemetry-detectors";
import { getChartDomain } from "./telemetry-thresholds";
import {
  groupTelemetryEvents,
  buildTelemetryEventMarkPoints,
  type TelemetryEventGroup,
} from "./telemetry-events";

export type TelemetryChartOption = ComposeOption<
  | AriaComponentOption
  | AxisPointerComponentOption
  | DataZoomComponentOption
  | GridComponentOption
  | LegendComponentOption
  | LineSeriesOption
  | ScatterSeriesOption
  | TooltipComponentOption
>;

export type ChartViewport =
  | { mode: "live" }
  | { mode: "absolute"; startMs: number; endMs: number };

export interface ChartTimeRange {
  fromMs?: number;
  toMs?: number;
}

export interface ChartNavigationState {
  range: ChartTimeRange;
  viewport: ChartViewport;
  inspectionDataEndMs?: number;
}

export const DEFAULT_CHART_NAVIGATION: ChartNavigationState = {
  range: {},
  viewport: { mode: "live" },
};

export const areChartNavigationStatesEqual = (
  left: ChartNavigationState,
  right: ChartNavigationState,
): boolean =>
  left.range.fromMs === right.range.fromMs &&
  left.range.toMs === right.range.toMs &&
  left.inspectionDataEndMs === right.inspectionDataEndMs &&
  left.viewport.mode === right.viewport.mode &&
  (left.viewport.mode === "live" ||
    (right.viewport.mode === "absolute" &&
      left.viewport.startMs === right.viewport.startMs &&
      left.viewport.endMs === right.viewport.endMs));

export type { MonitoringChartReading, TelemetryChartSeries } from "./types";


export interface MonitoringChartModel {
  readings: MonitoringChartReading[];
  secondarySeries: SecondaryChartSeries[];
  range: ChartTimeRange;
  extent?: [startMs: number, endMs: number];
}

export interface TelemetryChartModel {
  telemetry: TelemetryChartSeries;
  pendingTelemetry: TimeValue[];
  anomalyMarkers: TelemetryEventGroup[];
  secondarySeries: SecondaryChartSeries[];
  range: ChartTimeRange;
  extent?: [startMs: number, endMs: number];
}

export interface ChartThemeColors {
  foreground: string;
  mutedForeground: string;
  border: string;
  popover: string;
  popoverForeground: string;
  muted: string;
  primary: string;
  alarmBoundary?: string;
  alarmFill?: string;
}

interface BuildTelemetryChartModelInput {
  telemetryName: string;
  telemetryUnit?: string;
  telemetryColor: string;
  telemetry: TimeValue[];
  detectors: readonly TelemetryChartDetector[];
  pendingTelemetryTimestamps?: readonly number[];
  anomalyMarkers: AnomalyMarker[];
  selectedDetectorIds?: SelectedDetectorIds;
  range?: ChartTimeRange;
}

interface BuildTelemetryChartOptionInput {
  model: TelemetryChartModel;
  viewport: ChartViewport;
  timelineExtent?: readonly [startMs: number, endMs: number];
  timeZone: string;
  colors: ChartThemeColors;
  accessibleDescription: string;
  locale?: string;
  layout?: "standard" | "compact";
  valueType?: "number" | "boolean";
}

const dateTimeFormatters = new Map<string, Intl.DateTimeFormat>();
const numberFormatters = new Map<string, Intl.NumberFormat>();

const getDateTimeFormatter = (
  timeZone: string,
  locale: string | undefined,
  detail: "axis" | "tooltip",
): Intl.DateTimeFormat => {
  const key = `${locale ?? "default"}\u0000${timeZone}\u0000${detail}`;
  const cached = dateTimeFormatters.get(key);
  if (cached) return cached;

  const formatter = new Intl.DateTimeFormat(locale, {
    timeZone,
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: detail === "tooltip" ? "short" : undefined,
  });
  dateTimeFormatters.set(key, formatter);
  return formatter;
};

const getNumberFormatter = (locale?: string): Intl.NumberFormat => {
  const key = locale ?? "default";
  const cached = numberFormatters.get(key);
  if (cached) return cached;

  const formatter = new Intl.NumberFormat(locale, {
    maximumFractionDigits: 6,
  });
  numberFormatters.set(key, formatter);
  return formatter;
};

const formatNumber = (value: number): string => {
  if (!Number.isFinite(value)) return String(value);
  if (value === 0) return "0";
  const abs = Math.abs(value);
  if (abs < 0.001 || abs >= 1e6) return value.toExponential(2);
  const fractionDigits = Math.max(0, 3 - Math.floor(Math.log10(abs)));
  const formatted = value.toFixed(fractionDigits);
  return formatted.includes(".")
    ? formatted.replace(/0+$/, "").replace(/\.$/, "")
    : formatted;
};

export { formatNumber };

export const getLocalTimeZone = (): string =>
  Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

export const formatChartTime = (
  epochMilliseconds: number,
  timeZone: string,
  detail: "axis" | "tooltip" = "axis",
  locale?: string,
): string =>
  getDateTimeFormatter(timeZone, locale, detail).format(epochMilliseconds);

export const buildTelemetryChartModel = ({
  telemetryName,
  telemetryUnit,
  telemetryColor,
  telemetry,
  detectors,
  pendingTelemetryTimestamps = [],
  anomalyMarkers,
  selectedDetectorIds,
  range = {},
}: BuildTelemetryChartModelInput): TelemetryChartModel => {
  const telemetryTimes = telemetry.map(([time]) => time);
  const pendingTimes = new Set(pendingTelemetryTimestamps);
  const secondarySeries = buildSelectedDetectorSeries({ detectors, telemetryTimes, selectedDetectorIds, range });
  const startMs = telemetryTimes[0];
  const endMs = telemetryTimes[telemetryTimes.length - 1];

  return {
    telemetry: {
      id: "telemetry",
      name: telemetryName,
      unit: telemetryUnit,
      color: telemetryColor,
      data: telemetry,
    },
    pendingTelemetry: telemetry.filter(([time]) => pendingTimes.has(time)),
    anomalyMarkers: groupTelemetryEvents(anomalyMarkers),
    secondarySeries,
    range,
    extent: startMs !== undefined && endMs !== undefined ? [startMs, endMs] : undefined,
  };
};

type TooltipEntry = {
  seriesName?: unknown;
  value?: unknown;
  data?: unknown;
};

const readTimeValue = (value: unknown): TimeValue | undefined => {
  if (
    !Array.isArray(value) ||
    value.length < 2 ||
    value[1] === null ||
    !Number.isFinite(Number(value[0])) ||
    !Number.isFinite(Number(value[1]))
  ) {
    return undefined;
  }
  return [Number(value[0]), Number(value[1])];
};

const readObservationDetails = (data: unknown): { threshold: number | null; alarmActive: boolean } | undefined => {
  if (typeof data !== "object" || data === null || !("observation" in data)) return undefined;
  const { observation } = data;
  if (typeof observation !== "object" || observation === null ||
      !("threshold" in observation) || !("alarmActive" in observation) ||
      typeof observation.alarmActive !== "boolean") return undefined;
  const { threshold, alarmActive } = observation;
  if (threshold !== null && (typeof threshold !== "number" || !Number.isFinite(threshold))) return undefined;
  return { threshold, alarmActive };
};

export const formatTelemetryTooltip = (
  params: unknown,
  timeZone: string,
  units: ReadonlyMap<string, string>,
  locale?: string,
): string => {
  const entries = (Array.isArray(params) ? params : [params]).filter(
    (entry): entry is TooltipEntry => typeof entry === "object" && entry !== null,
  );
  const firstValue = entries.map((entry) => readTimeValue(entry.value)).find(Boolean);
  if (!firstValue) return "";

  const lines = [formatChartTime(firstValue[0], timeZone, "tooltip", locale)];
  const numberFormatter = getNumberFormatter(locale);
  for (const entry of entries) {
    const value = readTimeValue(entry.value);
    if (!value || typeof entry.seriesName !== "string") continue;
    const unit = units.get(entry.seriesName);
    const formattedValue = unit ? numberFormatter.format(value[1]) : formatNumber(value[1]);
    lines.push(
      `${entry.seriesName}: ${formattedValue}${unit ? ` ${unit}` : ""}`,
    );
    const observation = readObservationDetails(entry.data);
    if (observation) {
      lines.push(`Alarm threshold: ${observation.threshold !== null ? formatNumber(observation.threshold) : "unavailable"}`);
      lines.push(`Alarm: ${observation.alarmActive ? "active" : "inactive"}`);
    }
  }
  return lines.join("\n");
};

const axisLabelFormatterCache = new Map<string, (value: number) => string>();
const axisLabelFormatter = (
  timeZone: string,
  locale?: string,
  timeOnly = false,
): ((value: number) => string) => {
  const key = `${timeZone}\u0000${locale === undefined ? "\u0000" : locale}\u0000${timeOnly}`;
  const cached = axisLabelFormatterCache.get(key);
  if (cached) return cached;
  const date = new Intl.DateTimeFormat(locale, { timeZone, month: "short", day: "2-digit" });
  const time = new Intl.DateTimeFormat(locale, { timeZone, hour: "2-digit", minute: "2-digit", second: "2-digit",
    ...(timeOnly ? { hourCycle: "h23" as const } : {}) });
  const formatter = (value: number) => timeOnly ? time.format(Number(value))
    : `${date.format(Number(value))}\n${time.format(Number(value))}`;
  axisLabelFormatterCache.set(key, formatter);
  return formatter;
};

export const buildTelemetryChartOption = ({
  model, valueType = "number", ...options
}: BuildTelemetryChartOptionInput): TelemetryChartOption => buildMonitoringChartOption({
  ...options,
  model: { readings: [{ ...model.telemetry, valueType, pendingTelemetry: model.pendingTelemetry,
    anomalyMarkers: model.anomalyMarkers }], secondarySeries: model.secondarySeries, range: model.range, extent: model.extent },
});

type BuildMonitoringChartOptionInput = Omit<BuildTelemetryChartOptionInput, "model" | "valueType" | "layout"> & {
  model: MonitoringChartModel;
  layout?: "standard" | "compact" | "monitoring";
};

export const buildMonitoringChartOption = ({
  model,
  viewport,
  timelineExtent,
  timeZone,
  colors,
  accessibleDescription,
  locale,
  layout = "standard",
}: BuildMonitoringChartOptionInput): TelemetryChartOption => {
  const monitoring = layout === "monitoring";
  const compact = layout !== "standard";
  const hasStaticPane = model.secondarySeries.some((series) => series.pane === "static");
  const hasAdaptivePane = model.secondarySeries.some((series) => series.pane === "adaptive");
  const panes = [
    ...model.readings.map(reading => reading.id),
    ...(hasStaticPane ? ["static"] : []),
    ...(hasAdaptivePane ? ["adaptive"] : []),
  ] as const;
  const xAxisIndices = panes.map((_, index) => index);
  const domain = getChartDomain(timelineExtent ?? model.extent, model.range);
  const boundsByPane = new Map(model.secondarySeries.map((series) => [series.pane, series.bounds]));
  const units = new Map<string, string>();
  for (const reading of model.readings) if (reading.unit) units.set(reading.name, reading.unit);

  const grid: GridComponentOption[] = monitoring
    ? panes.map((_, index) => ({ left: 52, right: 18, top: 28 + index * 148, height: 100 }))
    : compact
    ? panes.map((_, index) => ({
        left: 44, right: 16,
        top: index === 0 ? 22 : 242 + (index - 1) * 164,
        ...(panes.length === 1 ? { bottom: 76 } : { height: index === 0 ? 164 : 112 }),
      }))
    : panes.length === 1
    ? [{ left: 68, right: 40, top: 58, bottom: 84 }]
    : panes.length === 2
      ? [
          { left: 68, right: 40, top: 58, height: 185 },
          { left: 68, right: 40, top: 290, height: 135 },
        ]
    : [
        { left: 68, right: 40, top: 58, height: 180 },
        { left: 68, right: 40, top: 288, height: 120 },
        { left: 68, right: 40, top: 450, height: 120 },
      ];
  const axisLabel = {
    color: colors.mutedForeground,
    fontSize: 11,
    formatter: axisLabelFormatter(timeZone, locale, compact),
    hideOverlap: true,
    alignMinLabel: "left" as const,
    alignMaxLabel: "right" as const,
  };
  const xAxis = xAxisIndices.map((_, index) => ({
    id: `${panes[index]}-time`,
    type: "time" as const,
    gridIndex: index,
    ...(compact ? { splitNumber: 4 } : {}),
    min: domain?.[0],
    max: domain?.[1],
    axisLabel: index < panes.length - 1 ? { show: false } : axisLabel,
    axisLine: { lineStyle: { color: colors.border } },
    axisTick: { show: false },
    splitLine: { show: false },
    axisPointer: { show: true, snap: false,
      ...(compact ? { label: { formatter: (params: { value: number | string | Date }) => axisLabelFormatter(timeZone, locale, true)(Number(params.value)) } } : {}),
    },
    name:
      !compact && index === panes.length - 1 ? `Local time (${timeZone})` : undefined,
    nameLocation: "middle" as const,
    nameGap: 35,
    nameTextStyle: { color: colors.mutedForeground, fontSize: 11 },
  }));
  const dataZoomRange =
    viewport.mode === "absolute"
      ? { startValue: viewport.startMs, endValue: viewport.endMs }
      : domain
        ? { startValue: domain[0], endValue: domain[1] }
        : { start: 0, end: 100 };

  const telemetrySeries: LineSeriesOption[] = model.readings.map((reading, index) => {
    const valueType = reading.valueType ?? "number";
    const telemetryValueExtent = reading.data.reduce<[number, number] | undefined>((extent, [, value]) =>
      extent ? [Math.min(extent[0], value), Math.max(extent[1], value)] : [value, value], undefined);
    return {
      id: reading.id,
      name: reading.name,
      type: "line",
      xAxisIndex: index,
      yAxisIndex: index,
      data: reading.data,
      smooth: false,
      step: valueType === "boolean" ? "end" : false,
      showSymbol: reading.data.length === 1,
      symbolSize: 5,
      ...(valueType === "number" ? { sampling: "lttb" } : {}),
      connectNulls: false,
      lineStyle: { color: reading.color, width: 2.25 },
      itemStyle: { color: reading.color },
      emphasis: { disabled: true },
      animation: false,
      markPoint: {
        symbol: "circle",
        label: { show: false },
        data: buildTelemetryEventMarkPoints(reading.anomalyMarkers, {
          timeZone, locale, colors,
          extent: viewport.mode === "absolute" ? [viewport.startMs, viewport.endMs] : domain,
          unit: reading.unit, telemetryValueExtent,
        }),
      },
      ...(reading.alarmTimes?.length ? { markLine: { silent: true, animation: false,
        symbol: ["none", "none"], label: { show: false }, lineStyle: { color: colors.alarmBoundary ?? "#dc2626", width: 1, opacity: 0.55 },
        data: reading.alarmTimes.map(time => ({ xAxis: time })),
      } } : {}),
    };
  });

  const pendingTelemetrySeries: ScatterSeriesOption[] = model.readings.flatMap((reading, index) =>
    reading.pendingTelemetry.length > 0
      ? [{
          id: `pending-${reading.id}`,
          name: "Awaiting anomaly score",
          type: "scatter",
          xAxisIndex: index,
          yAxisIndex: index,
          data: reading.pendingTelemetry,
          symbol: "emptyCircle",
          symbolSize: 8,
          itemStyle: {
            color: colors.popover,
            borderColor: colors.mutedForeground,
            borderWidth: 1.5,
          },
          emphasis: { disabled: true },
          animation: false,
          z: 5,
        }]
      : []);

  const secondarySeries: LineSeriesOption[] = model.secondarySeries.flatMap((series) => {
    const paneIndex = panes.indexOf(series.pane);
    const line = buildDetectionSeriesOption(
      series,
      paneIndex,
      domain,
      colors,
      (time) => formatChartTime(time, timeZone, "tooltip", locale),
      formatNumber,
    );
    if (!monitoring) return [line];
    line.markPoint = { ...line.markPoint, data: [...(line.markPoint?.data ?? []),
      ...series.data.flatMap(point => point.observation?.alarmFired && point.value[1] !== null ? [{
        name: "Alarm decision", coord: [point.value[0], point.value[1]], symbol: "circle", symbolSize: 6,
        itemStyle: { color: colors.alarmBoundary ?? "#dc2626" },
      }] : []),
    ] };
    return [line, buildThresholdSeriesOption(series, paneIndex, colors.alarmBoundary ?? "#dc2626")];
  });

  return {
    backgroundColor: "transparent",
    animation: false,
    aria: { enabled: true, description: accessibleDescription },
    color: [...model.readings.map(reading => reading.color), colors.primary],
    grid: grid.map((pane) => ({ ...pane, outerBoundsMode: "none" })),
    legend: compact ? { show: false } : {
      id: "telemetry-legend",
      type: "scroll",
      top: 10,
      left: 18,
      right: 18,
      textStyle: { color: colors.foreground, fontSize: 11 },
      pageTextStyle: { color: colors.mutedForeground },
    },
    axisPointer: {
      link: [{ xAxisIndex: "all" }],
      lineStyle: { color: colors.mutedForeground, type: "dashed" },
      label: {
        color: colors.popoverForeground,
        backgroundColor: colors.popover,
      },
    },
    tooltip: {
      trigger: "axis",
      renderMode: "richText",
      confine: true,
      appendToBody: false,
      backgroundColor: colors.popover,
      borderColor: colors.border,
      textStyle: { color: colors.popoverForeground, fontSize: 12 },
      axisPointer: { type: "cross" },
      formatter: (params: unknown) =>
        (monitoring ? formatMonitoringObservationTooltip(params, model.readings,
          time => formatChartTime(time, timeZone, "tooltip", locale), formatNumber) : undefined)
          ?? formatTelemetryTooltip(params, timeZone, units, locale),
    },
    xAxis,
    yAxis: [
      ...model.readings.map((reading, index) => ({
        id: `${reading.id}-values`,
        type: "value" as const,
        scale: true,
        boundaryGap: ["10%", "10%"] as [string, string],
        ...(reading.valueType === "boolean" ? { scale: false, min: 0, max: 1, interval: 1 } : {}),
        ...(compact ? { splitNumber: 4 } : {}),
        gridIndex: index,
        name: compact && !monitoring ? reading.unit : reading.unit
          ? `${reading.name} (${reading.unit})` : reading.name,
        nameTextStyle: { color: monitoring ? reading.color : colors.mutedForeground, fontSize: 11, align: "left" as const,
          ...(monitoring ? { overflow: "truncate" as const, width: 220 } : {}) },
        axisLabel: { color: colors.mutedForeground, fontSize: 11 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: colors.border, type: "dashed" as const } },
      })),
      ...(hasStaticPane
        ? [
            {
              id: "restarted-martingale-values",
              type: "log" as const,
              logBase: 10,
              min: boundsByPane.get("static")?.minimum,
              max: boundsByPane.get("static")?.maximum,
              gridIndex: panes.indexOf("static"),
              name: "Sequential evidence (log)",
              nameTextStyle: { color: colors.mutedForeground, fontSize: 11, align: "left" as const },
              axisLabel: {
                color: colors.mutedForeground,
                fontSize: 11,
                formatter: (value: number) => Number(value).toPrecision(2),
              },
              axisLine: { show: false },
              axisTick: { show: false },
              splitLine: {
                lineStyle: { color: colors.border, type: "dashed" as const },
              },
            },
          ]
        : []),
      ...(hasAdaptivePane
        ? [
            {
              id: "adaptive-score-values",
              type: "value" as const,
              scale: true,
              min: boundsByPane.get("adaptive")?.minimum,
              max: boundsByPane.get("adaptive")?.maximum,
              gridIndex: panes.indexOf("adaptive"),
              name: monitoring ? model.secondarySeries.find(series => series.pane === "adaptive")?.name : "Adaptive anomaly score",
              nameTextStyle: { color: colors.mutedForeground, fontSize: 11, align: "left" as const },
              axisLabel: { color: colors.mutedForeground, fontSize: 11,
                formatter: (value: number) => formatNumber(Number(value)), hideOverlap: true },
              axisLine: { show: false },
              axisTick: { show: false },
              splitLine: { lineStyle: { color: colors.border, type: "dashed" as const } },
            },
          ]
        : []),
    ],
    dataZoom: [
      {
        id: "telemetry-inside-zoom",
        type: "inside",
        ...(compact ? { throttle: 50 } : {}),
        xAxisIndex: xAxisIndices,
        filterMode: "none",
        ...(domain ? { rangeMode: ["value", "value"] as ["value", "value"] } : {}),
        zoomOnMouseWheel: "ctrl",
        moveOnMouseWheel: compact ? "shift" : true,
        moveOnMouseMove: true,
        preventDefaultMouseMove: true,
        ...dataZoomRange,
      },
      {
        id: "telemetry-slider-zoom",
        type: "slider",
        ...(compact ? { throttle: 50, moveHandleSize: 0 } : {}),
        xAxisIndex: xAxisIndices,
        filterMode: "none",
        ...(domain ? { rangeMode: ["value", "value"] as ["value", "value"] } : {}),
        bottom: 8,
        height: compact ? 26 : 18,
        showDetail: false,
        borderColor: colors.border,
        backgroundColor: colors.muted,
        fillerColor: chartColor.modifyAlpha(colors.primary, 0.1) ?? colors.muted,
        handleStyle: { color: colors.popover, borderColor: colors.primary, borderWidth: 1 },
        moveHandleStyle: { color: colors.border },
        emphasis: {
          handleStyle: { color: colors.popover, borderColor: colors.primary },
          moveHandleStyle: { color: colors.primary },
        },
        dataBackground: {
          lineStyle: { color: colors.mutedForeground },
          areaStyle: { color: colors.muted },
        },
        selectedDataBackground: {
          lineStyle: { color: model.readings[0]?.color ?? colors.primary },
          areaStyle: { color: model.readings[0]?.color ?? colors.primary, opacity: 0.15 },
        },
        ...dataZoomRange,
      },
    ],
    series: [
      ...telemetrySeries,
      ...pendingTelemetrySeries,
      ...secondarySeries,
    ],
  };
};
