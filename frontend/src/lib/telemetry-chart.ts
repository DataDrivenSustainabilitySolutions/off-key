import type { LineSeriesOption } from "echarts/charts";
import type {
  AriaComponentOption,
  AxisPointerComponentOption,
  DataZoomComponentOption,
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
} from "echarts/components";
import type { ComposeOption } from "echarts/core";

import {
  formatAnomalyValue,
  getAnomalyValueLabel,
} from "@/lib/anomaly-semantics";
import type { AnomalyMarker, RedZone } from "@/lib/anomaly-utils";
import type { TelemetryDataPoint } from "@/types/charger";
import type {
  MartingaleAlarmStatistic,
  MartingaleBettingFunction,
  MartingaleTrackerResult,
  MonitoringChartEvidence,
} from "@/types/monitoring";

export type TelemetryChartOption = ComposeOption<
  | AriaComponentOption
  | AxisPointerComponentOption
  | DataZoomComponentOption
  | GridComponentOption
  | LegendComponentOption
  | LineSeriesOption
  | TooltipComponentOption
>;

export type TimeValue = [epochMilliseconds: number, value: number];

export type ChartViewport =
  | { mode: "live" }
  | { mode: "absolute"; startMs: number; endMs: number };

export interface TelemetryChartSeries {
  id: "telemetry";
  name: string;
  unit?: string;
  color: string;
  data: TimeValue[];
}

export interface SecondaryChartSeries {
  id: string;
  serviceId: string;
  name: string;
  threshold: number;
  color: string;
  data: TimeValue[];
}

export interface ChartAnomalyMarker {
  timeMs: number;
  value: number;
  anomaly: AnomalyMarker["anomaly"];
  color: string;
  size: number;
  opacity: number;
}

export interface TelemetryChartModel {
  telemetry: TelemetryChartSeries;
  anomalyZones: Array<{
    startMs: number;
    endMs: number;
    anomalyCount: number;
  }>;
  anomalyMarkers: ChartAnomalyMarker[];
  secondarySeries: SecondaryChartSeries[];
  extent?: [startMs: number, endMs: number];
}

export interface ChartThemeColors {
  foreground: string;
  mutedForeground: string;
  border: string;
  popover: string;
  popoverForeground: string;
  muted: string;
}

interface BuildTelemetryChartModelInput {
  telemetryName: string;
  telemetryUnit?: string;
  telemetryColor: string;
  telemetry: TelemetryDataPoint[];
  evidence: MonitoringChartEvidence[];
  anomalyZones: RedZone[];
  anomalyMarkers: AnomalyMarker[];
}

interface BuildTelemetryChartOptionInput {
  model: TelemetryChartModel;
  viewport: ChartViewport;
  timeZone: string;
  colors: ChartThemeColors;
  accessibleDescription: string;
  locale?: string;
}

const SECONDARY_COLORS = [
  "#059669",
  "#7c3aed",
  "#dc2626",
  "#0284c7",
] as const;

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

const buildSecondarySeries = (
  evidence: MonitoringChartEvidence[],
): SecondaryChartSeries[] => {
  const byTracker = new Map<
    string,
    {
      serviceId: string;
      trackerId: string;
      bettingFunction: MartingaleBettingFunction;
      alarmStatistic: MartingaleAlarmStatistic;
      points: TimeValue[];
      threshold: number;
    }
  >();

  evidence.forEach((observation) => {
    const time = toFiniteTime(observation.timestamp);
    if (time === undefined) return;
    const legacyTracker: MartingaleTrackerResult = {
      tracker_id: "primary",
      betting_function: "power",
      betting_parameters: {},
      alarm_statistic: "restarted_martingale",
      statistic_value: observation.restarted_martingale,
      statistic_is_infinite: false,
      log_statistic_value: null,
      statistics: {},
      e_value: null,
      e_value_is_infinite: false,
      log_e_value: null,
      threshold: observation.threshold,
      alarm_fired: observation.alarm,
      alarm_active: observation.alarm,
      alarm_count: 0,
      tested_count: observation.sequence_number,
    };
    const trackerResults = observation.tracker_results?.length
      ? observation.tracker_results
      : [legacyTracker];

    trackerResults.forEach((tracker) => {
      const value = tracker.statistic_value;
      if (value === null || !Number.isFinite(value) || value <= 0) return;
      const key = `${observation.service_id}\u0000${tracker.tracker_id}`;
      const existing = byTracker.get(key) ?? {
        serviceId: observation.service_id,
        trackerId: tracker.tracker_id,
        bettingFunction: tracker.betting_function,
        alarmStatistic: tracker.alarm_statistic,
        points: [],
        threshold: tracker.threshold,
      };
      existing.points.push([time, value]);
      if (Number.isFinite(tracker.threshold) && tracker.threshold > 0) {
        existing.threshold = tracker.threshold;
      }
      byTracker.set(key, existing);
    });
  });

  const statisticLabels: Record<MartingaleAlarmStatistic, string> = {
    martingale: "All-history martingale",
    restarted_martingale: "Restarted e-process",
    cusum: "CUSUM",
    shiryaev_roberts: "Shiryaev-Roberts",
  };
  const bettingLabels: Record<MartingaleBettingFunction, string> = {
    power: "Power",
    simple_mixture: "Simple mixture",
    simple_jumper: "Simple jumper",
  };

  return [...byTracker.values()].map((series, index) => {
    const methodSuffix =
      series.bettingFunction === "power" && series.trackerId === "primary"
        ? ""
        : ` (${bettingLabels[series.bettingFunction]} · ${series.trackerId})`;
    const isLegacyPrimary =
      series.bettingFunction === "power" &&
      series.trackerId === "primary" &&
      series.alarmStatistic === "restarted_martingale";
    return {
      id: isLegacyPrimary
        ? `restarted-martingale:${series.serviceId}`
        : `martingale:${series.serviceId}:${series.trackerId}`,
      serviceId: series.serviceId,
      name: `${statisticLabels[series.alarmStatistic]}${methodSuffix} ${series.serviceId.slice(0, 8)}`,
      threshold: series.threshold,
      color:
        SECONDARY_COLORS[index % SECONDARY_COLORS.length] ?? SECONDARY_COLORS[0],
      data: series.points.sort((left, right) => left[0] - right[0]),
    };
  });
};

export const buildTelemetryChartModel = ({
  telemetryName,
  telemetryUnit,
  telemetryColor,
  telemetry,
  evidence,
  anomalyZones,
  anomalyMarkers,
}: BuildTelemetryChartModelInput): TelemetryChartModel => {
  const telemetryData = normalizeTelemetry(telemetry);
  const secondarySeries = buildSecondarySeries(evidence);

  return {
    telemetry: {
      id: "telemetry",
      name: telemetryName,
      unit: telemetryUnit,
      color: telemetryColor,
      data: telemetryData,
    },
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
    anomalyMarkers: anomalyMarkers
      .filter(
        (marker) => Number.isFinite(marker.time) && Number.isFinite(marker.value),
      )
      .map((marker) => ({
        timeMs: marker.time,
        value: marker.value,
        anomaly: marker.anomaly,
        color: marker.style.color,
        size: marker.style.radius * 2,
        opacity: marker.style.opacity,
      })),
    secondarySeries,
    extent: getExtent(telemetryData, secondarySeries),
  };
};

type TooltipEntry = {
  seriesName?: unknown;
  value?: unknown;
};

const readTimeValue = (value: unknown): TimeValue | undefined => {
  if (
    !Array.isArray(value) ||
    value.length < 2 ||
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
    lines.push(
      `${entry.seriesName}: ${numberFormatter.format(value[1])}${unit ? ` ${unit}` : ""}`,
    );
  }
  return lines.join("\n");
};

const formatAnomalyTooltip = (
  marker: ChartAnomalyMarker,
  timeZone: string,
  locale?: string,
): string => {
  const anomaly = marker.anomaly;
  return [
    `Anomaly: ${anomaly.anomaly_type}`,
    `${getAnomalyValueLabel(anomaly.value_type)}: ${formatAnomalyValue(anomaly.anomaly_value, anomaly.value_type)}`,
    `Time: ${formatChartTime(marker.timeMs, timeZone, "tooltip", locale)}`,
    `Type: ${anomaly.telemetry_type}`,
    `Sensors: ${anomaly.sensor_set?.join(", ") || "not recorded"}`,
  ].join("\n");
};

const axisLabelFormatter = (
  timeZone: string,
  locale?: string,
): ((value: number) => string) =>
  (value) => formatChartTime(Number(value), timeZone, "axis", locale);

export const buildTelemetryChartOption = ({
  model,
  viewport,
  timeZone,
  colors,
  accessibleDescription,
  locale,
}: BuildTelemetryChartOptionInput): TelemetryChartOption => {
  const hasSecondaryPane = model.secondarySeries.length > 0;
  const secondaryMaximum = Math.max(
    ...model.secondarySeries.flatMap((series) => [
      series.threshold,
      ...series.data.map(([, value]) => value),
    ]),
  );
  const xAxisIndices = hasSecondaryPane ? [0, 1] : [0];
  const units = new Map<string, string>();
  if (model.telemetry.unit) units.set(model.telemetry.name, model.telemetry.unit);

  const grid: GridComponentOption[] = hasSecondaryPane
    ? [
        { left: 68, right: 34, top: 58, height: 142 },
        { left: 68, right: 34, top: 244, height: 102 },
      ]
    : [{ left: 68, right: 34, top: 58, bottom: 66 }];
  const axisLabel = {
    color: colors.mutedForeground,
    fontSize: 11,
    formatter: axisLabelFormatter(timeZone, locale),
    hideOverlap: true,
  };
  const xAxis = xAxisIndices.map((_, index) => ({
    id: index === 0 ? "telemetry-time" : "secondary-time",
    type: "time" as const,
    gridIndex: index,
    min: model.extent?.[0],
    max: model.extent?.[1],
    axisLabel: hasSecondaryPane && index === 0 ? { show: false } : axisLabel,
    axisLine: { lineStyle: { color: colors.border } },
    axisTick: { show: false },
    splitLine: { show: false },
    axisPointer: { show: true, snap: false },
    name:
      !hasSecondaryPane || index === 1 ? `Local time (${timeZone})` : undefined,
    nameLocation: "middle" as const,
    nameGap: 42,
    nameTextStyle: { color: colors.mutedForeground, fontSize: 11 },
  }));
  const dataZoomRange =
    viewport.mode === "absolute"
      ? { startValue: viewport.startMs, endValue: viewport.endMs }
      : model.extent
        ? { startValue: model.extent[0], endValue: model.extent[1] }
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
    markArea: {
      silent: true,
      itemStyle: { color: "rgba(220, 38, 38, 0.1)" },
      data: model.anomalyZones.map((zone) => [
        {
          name: `${zone.anomalyCount} anomal${zone.anomalyCount === 1 ? "y" : "ies"}`,
          xAxis: zone.startMs,
        },
        { xAxis: zone.endMs },
      ]),
    },
    markPoint: {
      symbol: "circle",
      label: { show: false },
      data: model.anomalyMarkers.map((marker) => ({
        name: "Anomaly",
        coord: [marker.timeMs, marker.value],
        symbolSize: Math.max(marker.size, 8),
        itemStyle: {
          color: marker.color,
          borderColor: "#7f1d1d",
          borderWidth: 1,
          opacity: marker.opacity,
        },
        tooltip: {
          formatter: () => formatAnomalyTooltip(marker, timeZone, locale),
        },
      })),
    },
  };

  const secondarySeries: LineSeriesOption[] = model.secondarySeries.map(
    (series) => ({
      id: series.id,
      name: series.name,
      type: "line",
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: series.data,
      smooth: false,
      step: "end",
      showSymbol: false,
      connectNulls: false,
      lineStyle: { color: series.color, width: 2 },
      itemStyle: { color: series.color },
      emphasis: { disabled: true },
      animation: false,
      markLine: {
        silent: true,
        symbol: ["none", "none"],
        lineStyle: { color: "#dc2626", type: "dashed", width: 1.5 },
        label: {
          show: true,
          formatter: `Alarm threshold ${series.threshold}`,
          position: "insideEndTop",
          color: colors.mutedForeground,
          fontSize: 10,
        },
        data: [{ yAxis: series.threshold }],
      },
    }),
  );

  return {
    animation: false,
    aria: { enabled: true, description: accessibleDescription },
    color: [model.telemetry.color, ...model.secondarySeries.map(({ color }) => color)],
    grid,
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
        formatTelemetryTooltip(params, timeZone, units, locale),
    },
    xAxis,
    yAxis: [
      {
        id: "telemetry-values",
        type: "value",
        gridIndex: 0,
        name: model.telemetry.unit
          ? `${model.telemetry.name} (${model.telemetry.unit})`
          : model.telemetry.name,
        nameTextStyle: { color: colors.mutedForeground, fontSize: 11 },
        axisLabel: { color: colors.mutedForeground, fontSize: 11 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: colors.border, type: "dashed" } },
      },
      ...(hasSecondaryPane
        ? [
            {
              id: "restarted-martingale-values",
              type: "log" as const,
              logBase: 10,
              max: secondaryMaximum,
              gridIndex: 1,
              name: "Sequential evidence",
              nameTextStyle: { color: colors.mutedForeground, fontSize: 11 },
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
    series: [telemetrySeries, ...secondarySeries],
  };
};
