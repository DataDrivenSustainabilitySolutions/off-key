import type { LineSeriesOption, ScatterSeriesOption } from "echarts/charts";
import type {
  AriaComponentOption,
  AxisPointerComponentOption,
  DataZoomComponentOption,
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
} from "echarts/components";
import type { ComposeOption } from "echarts/core";
import { buildDetectionSeriesOption } from "@/lib/telemetry-detection-series";

import type { AnomalyMarker, RedZone } from "@/lib/anomaly-utils";
import type { TelemetryDataPoint } from "@/types/charger";
import type { MonitoringChartEvidence } from "@/types/monitoring";
import {
  collectTelemetryChartDetectors,
  selectDetectorSeries,
  type ChartDetector,
  type SecondaryChartSeries,
  type SelectedDetectorIds,
} from "@/lib/telemetry-detectors";
import {
  getChartDomain,
  getDetectionValueBounds,
} from "@/lib/telemetry-thresholds";
import {
  groupTelemetryEvents,
  buildTelemetryEventMarkPoints,
  type TelemetryEventGroup,
} from "@/lib/telemetry-events";

export { getDefaultDetectorId, collectTelemetryChartDetectors } from "@/lib/telemetry-detectors";
export type { ChartDetector, SecondaryChartSeries, SelectedDetectorIds } from "@/lib/telemetry-detectors";

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

export type TimeValue = [epochMilliseconds: number, value: number];
export type NullableTimeValue = [epochMilliseconds: number, value: number | null];

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

export interface TelemetryChartSeries {
  id: "telemetry";
  name: string;
  unit?: string;
  color: string;
  data: TimeValue[];
}

export type ChartAnomalyMarker = TelemetryEventGroup;

export interface TelemetryChartModel {
  telemetry: TelemetryChartSeries;
  pendingTelemetry: TimeValue[];
  anomalyZones: Array<{
    startMs: number;
    endMs: number;
    anomalyCount: number;
  }>;
  anomalyMarkers: ChartAnomalyMarker[];
  detectors: ChartDetector[];
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
  telemetryType: string;
  telemetryName: string;
  telemetryUnit?: string;
  telemetryColor: string;
  telemetry: TelemetryDataPoint[];
  evidence: MonitoringChartEvidence[];
  pendingTelemetryTimestamps?: readonly number[];
  anomalyZones: RedZone[];
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

const toFiniteTime = (timestamp: string): number | undefined => {
  const time = Date.parse(timestamp);
  return Number.isFinite(time) ? time : undefined;
};

const normalizeTelemetry = (points: TelemetryDataPoint[]): TimeValue[] => {
  const valuesByTime = new Map<number, number>();
  for (const point of points) {
    const time = toFiniteTime(point.timestamp);
    if (time === undefined || !Number.isFinite(point.value)) continue;
    valuesByTime.set(time, point.value);
  }

  return [...valuesByTime.entries()].sort((left, right) => left[0] - right[0]);
};

const getExtent = (
  telemetry: TimeValue[],
  secondarySeries: SecondaryChartSeries[],
): [number, number] | undefined => {
  let minimum = Number.POSITIVE_INFINITY;
  let maximum = Number.NEGATIVE_INFINITY;

  for (const [time] of telemetry) {
    minimum = Math.min(minimum, time);
    maximum = Math.max(maximum, time);
  }
  for (const series of secondarySeries) {
    for (const [time] of series.data) {
      minimum = Math.min(minimum, time);
      maximum = Math.max(maximum, time);
    }
  }

  return Number.isFinite(minimum) && Number.isFinite(maximum)
    ? [minimum, maximum]
    : undefined;
};

export const buildTelemetryChartModel = ({
  telemetryType,
  telemetryName,
  telemetryUnit,
  telemetryColor,
  telemetry,
  evidence,
  pendingTelemetryTimestamps = [],
  anomalyZones,
  anomalyMarkers,
  selectedDetectorIds,
  range = {},
}: BuildTelemetryChartModelInput): TelemetryChartModel => {
  const telemetryData = normalizeTelemetry(telemetry);
  const telemetryTimes = telemetryData.map(([time]) => time);
  const pendingTimes = new Set(pendingTelemetryTimestamps);
  const allDetectors = collectTelemetryChartDetectors({ evidence, telemetryType, telemetryTimes, range })
    .map((series) => ({ ...series, color: telemetryColor }));
  const secondarySeries = selectDetectorSeries(allDetectors, selectedDetectorIds);
  const events = groupTelemetryEvents(anomalyMarkers);

  return {
    telemetry: {
      id: "telemetry",
      name: telemetryName,
      unit: telemetryUnit,
      color: telemetryColor,
      data: telemetryData,
    },
    pendingTelemetry: telemetryData.filter(([time]) => pendingTimes.has(time)),
    anomalyZones: anomalyZones
      .filter(
        (zone) =>
          Number.isFinite(zone.startMs) &&
          Number.isFinite(zone.endMs) &&
          zone.endMs >= zone.startMs,
      )
      .map((zone) => ({
        startMs: zone.startMs,
        endMs: zone.endMs,
        anomalyCount: zone.anomalies.length,
      })),
    anomalyMarkers: events,
    detectors: allDetectors.map(({ id, serviceId, trackerId, name, pane }) => ({ id, serviceId, trackerId, name, pane })),
    secondarySeries,
    range,
    extent: getExtent(telemetryData, secondarySeries),
  };
};

type TooltipEntry = {
  seriesName?: unknown;
  seriesId?: unknown;
  value?: unknown;
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

export const formatTelemetryTooltip = (
  params: unknown,
  timeZone: string,
  units: ReadonlyMap<string, string>,
  locale?: string,
  detectors: readonly SecondaryChartSeries[] = [],
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
    const detector = detectors.find((series) => series.id === entry.seriesId);
    const observation = detector?.observations.slice().reverse().find((item) => item.timeMs === value[0]);
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
): ((value: number) => string) => {
  const key = `${timeZone}\u0000${locale === undefined ? "\u0000" : locale}`;
  const cached = axisLabelFormatterCache.get(key);
  if (cached) return cached;
  const date = new Intl.DateTimeFormat(locale, { timeZone, month: "short", day: "2-digit" });
  const time = new Intl.DateTimeFormat(locale, { timeZone, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const formatter = (value: number) => `${date.format(Number(value))}\n${time.format(Number(value))}`;
  axisLabelFormatterCache.set(key, formatter);
  return formatter;
};

export const buildTelemetryChartOption = ({
  model,
  viewport,
  timelineExtent,
  timeZone,
  colors,
  accessibleDescription,
  locale,
}: BuildTelemetryChartOptionInput): TelemetryChartOption => {
  const hasStaticPane = model.secondarySeries.some((series) => series.pane === "static");
  const hasAdaptivePane = model.secondarySeries.some((series) => series.pane === "adaptive");
  const panes = [
    "telemetry",
    ...(hasStaticPane ? ["static"] : []),
    ...(hasAdaptivePane ? ["adaptive"] : []),
  ] as const;
  const xAxisIndices = panes.map((_, index) => index);
  const domain = getChartDomain(timelineExtent ?? model.extent, model.range);
  const boundsByPane = new Map(model.secondarySeries.map((series) => [
    series.pane, getDetectionValueBounds(series.scale, series.data, series.thresholds),
  ]));
  const units = new Map<string, string>();
  if (model.telemetry.unit) units.set(model.telemetry.name, model.telemetry.unit);
  const telemetryValueExtent = model.telemetry.data.reduce<[number, number] | undefined>((extent, [, value]) => {
    if (!Number.isFinite(value)) return extent;
    return extent ? [Math.min(extent[0], value), Math.max(extent[1], value)] : [value, value];
  }, undefined);

  const grid: GridComponentOption[] = panes.length === 1
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
    formatter: axisLabelFormatter(timeZone, locale),
    hideOverlap: true,
    alignMinLabel: "left" as const,
    alignMaxLabel: "right" as const,
  };
  const xAxis = xAxisIndices.map((_, index) => ({
    id: `${panes[index]}-time`,
    type: "time" as const,
    gridIndex: index,
    min: domain?.[0],
    max: domain?.[1],
    axisLabel: index < panes.length - 1 ? { show: false } : axisLabel,
    axisLine: { lineStyle: { color: colors.border } },
    axisTick: { show: false },
    splitLine: { show: false },
    axisPointer: { show: true, snap: false },
    name:
      index === panes.length - 1 ? `Local time (${timeZone})` : undefined,
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

  const telemetrySeries: LineSeriesOption = {
    id: model.telemetry.id,
    name: model.telemetry.name,
    type: "line",
    xAxisIndex: 0,
    yAxisIndex: 0,
    data: model.telemetry.data,
    smooth: false,
    step: false,
    showSymbol: false,
    connectNulls: false,
    lineStyle: { color: model.telemetry.color, width: 2.25 },
    itemStyle: { color: model.telemetry.color },
    emphasis: { disabled: true },
    animation: false,
    markPoint: {
      symbol: "circle",
      label: { show: false },
      data: buildTelemetryEventMarkPoints(model.anomalyMarkers, {
        timeZone,
        locale,
        colors,
        extent: viewport.mode === "absolute" ? [viewport.startMs, viewport.endMs] : domain,
        unit: model.telemetry.unit,
        telemetryValueExtent,
      }),
    },
  };

  const pendingTelemetrySeries: ScatterSeriesOption | undefined =
    model.pendingTelemetry.length > 0
      ? {
          id: "pending-telemetry",
          name: "Awaiting anomaly score",
          type: "scatter",
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: model.pendingTelemetry,
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
        }
      : undefined;

  const secondarySeries: LineSeriesOption[] = model.secondarySeries.map((series) =>
    buildDetectionSeriesOption(
      series,
      panes.indexOf(series.pane),
      boundsByPane.get(series.pane)!,
      domain,
      colors,
      (time) => formatChartTime(time, timeZone, "tooltip", locale),
      formatNumber,
    ),
  );

  return {
    animation: false,
    aria: { enabled: true, description: accessibleDescription },
    color: [model.telemetry.color, ...model.secondarySeries.map(({ color }) => color)],
    grid: grid.map((pane) => ({ ...pane, outerBoundsMode: "none" })),
    legend: {
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
        formatTelemetryTooltip(params, timeZone, units, locale, model.secondarySeries),
    },
    xAxis,
    yAxis: [
      {
        id: "telemetry-values",
        type: "value",
        scale: true,
        boundaryGap: ["10%", "10%"],
        gridIndex: 0,
        name: model.telemetry.unit
          ? `${model.telemetry.name} (${model.telemetry.unit})`
          : model.telemetry.name,
        nameTextStyle: { color: colors.mutedForeground, fontSize: 11, align: "left" as const },
        axisLabel: { color: colors.mutedForeground, fontSize: 11 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: colors.border, type: "dashed" } },
      },
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
              name: "Adaptive anomaly score",
              nameTextStyle: { color: colors.mutedForeground, fontSize: 11, align: "left" as const },
              axisLabel: { color: colors.mutedForeground, fontSize: 11 },
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
        xAxisIndex: xAxisIndices,
        filterMode: "none",
        zoomOnMouseWheel: "ctrl",
        moveOnMouseWheel: true,
        moveOnMouseMove: true,
        preventDefaultMouseMove: true,
        ...dataZoomRange,
      },
      {
        id: "telemetry-slider-zoom",
        type: "slider",
        xAxisIndex: xAxisIndices,
        filterMode: "none",
        bottom: 8,
        height: 18,
        showDetail: false,
        borderColor: colors.border,
        backgroundColor: colors.muted,
        fillerColor: "rgba(15, 159, 142, 0.18)",
        dataBackground: {
          lineStyle: { color: colors.mutedForeground },
          areaStyle: { color: colors.muted },
        },
        selectedDataBackground: {
          lineStyle: { color: model.telemetry.color },
          areaStyle: { color: model.telemetry.color, opacity: 0.15 },
        },
        ...dataZoomRange,
      },
    ],
    series: [
      telemetrySeries,
      ...(pendingTelemetrySeries ? [pendingTelemetrySeries] : []),
      ...secondarySeries,
    ],
  };
};
