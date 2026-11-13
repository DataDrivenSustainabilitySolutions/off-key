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
import { getPauseLimit, type TimeValue } from "./telemetry-data";
import type { MonitoringChartReading, TelemetryChartSeries } from "./types";
import {
  alarmText,
  buildSelectedDetectorSeries,
  type TelemetryChartDetector,
  type SecondaryChartSeries,
  type SelectedDetectorIds,
} from "./telemetry-detectors";
import { getChartDomain, type DetectionValueBounds } from "./telemetry-thresholds";
import { forecastIntervalText, type DetectorInputSeries } from "./detector-inputs";
import { localMidnights, timeAxisLabelFormatter } from "./time-axis";
import { bandSeries, historyBandSeries, historyChartData } from "./history-presentation";
import type { HistoryPoint, TelemetryHistory } from "@/types/telemetry-history";
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

type ChartViewport =
  | { mode: "live" }
  | { mode: "absolute"; startMs: number; endMs: number };

interface ChartTimeRange {
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



export interface MonitoringChartModel {
  readings: MonitoringChartReading[];
  /** The features the detectors scored, in their own pane under the readings. */
  detectorInputs?: DetectorInputSeries[];
  secondarySeries: SecondaryChartSeries[];
  range: ChartTimeRange;
  extent?: [startMs: number, endMs: number];
}

export interface TelemetryChartModel {
  telemetry: TelemetryChartSeries;
  pendingTelemetry: TimeValue[];
  anomalyMarkers: TelemetryEventGroup[];
  detectorInputs?: DetectorInputSeries[];
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
  /** Categorical colours for detector inputs. */
  seriesPalette?: readonly string[];
  alarmBoundary?: string;
  alarmFill?: string;
}

interface BuildTelemetryChartModelInput {
  telemetryName: string;
  telemetryUnit?: string;
  telemetryColor: string;
  telemetry: TimeValue[];
  presentation?: TelemetryHistory;
  /** Times that have a reading on the chart, when means stand for samples that are not loaded. */
  detectionTimes?: readonly number[];
  detectors: readonly TelemetryChartDetector[];
  pendingTelemetryTimestamps?: readonly number[];
  anomalyMarkers: AnomalyMarker[];
  detectorInputs?: DetectorInputSeries[];
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

/** Distinct from the reading colours, in light and dark. */
const DEFAULT_SERIES_PALETTE = ["#2f6db3", "#c0562e", "#7a4fb0", "#2e8a57", "#a0711a", "#a43f74", "#3f8590", "#6b6b6b"];

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

type RangeFormat = Intl.DateTimeFormat & { formatRange?: (startMs: number, endMs: number) => string };

/** A span of time: the parts both ends share are named once where the locale can, and so is the zone. */
const formatChartInterval = (startMs: number, endMs: number, timeZone: string, locale?: string): string => {
  const plain: RangeFormat = getDateTimeFormatter(timeZone, locale, "axis");
  const zone = getDateTimeFormatter(timeZone, locale, "tooltip").formatToParts(endMs)
    .find((part) => part.type === "timeZoneName")?.value;
  const span = plain.formatRange?.(startMs, endMs) ?? `${plain.format(startMs)} – ${plain.format(endMs)}`;
  return zone ? `${span} ${zone}` : span;
};

export const buildTelemetryChartModel = ({
  telemetryName,
  telemetryUnit,
  telemetryColor,
  telemetry,
  presentation,
  detectionTimes,
  detectors,
  pendingTelemetryTimestamps = [],
  anomalyMarkers,
  detectorInputs = [],
  selectedDetectorIds,
  range = {},
}: BuildTelemetryChartModelInput): TelemetryChartModel => {
  const telemetryTimes = telemetry.map(([time]) => time);
  const pendingTimes = new Set(pendingTelemetryTimestamps);
  const secondarySeries = buildSelectedDetectorSeries({ detectors, telemetryTimes: detectionTimes ?? telemetryTimes, selectedDetectorIds, range });
  const startMs = telemetryTimes[0];
  const endMs = telemetryTimes[telemetryTimes.length - 1];

  return {
    telemetry: {
      id: "telemetry",
      name: telemetryName,
      unit: telemetryUnit,
      color: telemetryColor,
      data: telemetry,
      presentation,
    },
    pendingTelemetry: telemetry.filter(([time]) => pendingTimes.has(time)),
    anomalyMarkers: groupTelemetryEvents(anomalyMarkers),
    detectorInputs,
    secondarySeries,
    range,
    extent: presentation?.extent ? [Date.parse(presentation.extent[0]), Date.parse(presentation.extent[1])]
      : startMs !== undefined && endMs !== undefined ? [startMs, endMs] : undefined,
  };
};

type TooltipEntry = {
  seriesId?: unknown;
  seriesName?: unknown;
  value?: unknown;
  data?: unknown;
  axisValue?: unknown;
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

const readObservationDetails = (data: unknown): { threshold: number | null; alarmActive: boolean; alarmMuted: boolean } | undefined => {
  if (typeof data !== "object" || data === null || !("observation" in data)) return undefined;
  const { observation } = data;
  if (typeof observation !== "object" || observation === null ||
      !("threshold" in observation) || !("alarmActive" in observation) ||
      typeof observation.alarmActive !== "boolean") return undefined;
  const { threshold, alarmActive } = observation;
  if (threshold !== null && (typeof threshold !== "number" || !Number.isFinite(threshold))) return undefined;
  return { threshold, alarmActive, alarmMuted: "alarmMuted" in observation && observation.alarmMuted === true };
};

const readSummary = (data: unknown): HistoryPoint | undefined =>
  typeof data === "object" && data !== null && "summary" in data ? (data as { summary?: HistoryPoint }).summary : undefined;

const readPeakCount = (data: unknown): number => typeof data === "object" && data !== null && "peak" in data
  ? (data as { peak?: { count: number } }).peak?.count ?? 1 : 1;

/** A range reads "0–10"; a minus sign beside the dash would not, so negative bounds read "-3 to -1". */
const formatRange = (minimum: number, maximum: number): string => minimum < 0 || maximum < 0
  ? `${formatNumber(minimum)} to ${formatNumber(maximum)}` : `${formatNumber(minimum)}–${formatNumber(maximum)}`;

/**
 * `reach` holds, per series id, how far from the pointer a point may lie and still
 * be named. The axis pointer offers the nearest point of every series, however
 * distant; a series only speaks where its line is drawn. `means` names the series
 * whose plain points are interval means.
 */
export const formatTelemetryTooltip = (
  params: unknown,
  timeZone: string,
  units: ReadonlyMap<string, string>,
  locale?: string,
  reach?: ReadonlyMap<string, number>,
  means?: ReadonlySet<string>,
): string => {
  const entries = (Array.isArray(params) ? params : [params]).filter(
    (entry): entry is TooltipEntry => typeof entry === "object" && entry !== null,
  ).filter((entry) => {
    const seriesId = String(entry.seriesId);
    // Bands and lone-sample dots only draw what their own line names.
    if (["forecast-band:", "history-band:", "history-dot:"].some((prefix) => seriesId.startsWith(prefix))) return false;
    const value = readTimeValue(entry.value), limit = reach?.get(seriesId);
    const pointer = entry.axisValue === undefined ? NaN : Number(entry.axisValue);
    return !value || limit === undefined || !Number.isFinite(pointer) || Math.abs(value[0] - pointer) <= limit;
  });
  const firstValue = entries.map((entry) => readTimeValue(entry.value)).find(Boolean);
  if (!firstValue) return "";

  // Means share their interval, so it heads the tooltip once instead of following each reading.
  const interval = entries.map((entry) => readSummary(entry.data)).find((summary) => summary?.start && summary.end);
  const lines = [interval
    ? formatChartInterval(Date.parse(interval.start!), Date.parse(interval.end!), timeZone, locale)
    : formatChartTime(firstValue[0], timeZone, "tooltip", locale)];
  const numberFormatter = getNumberFormatter(locale);
  for (const entry of entries) {
    const value = readTimeValue(entry.value);
    if (!value || typeof entry.seriesName !== "string") continue;
    const seriesId = typeof entry.seriesId === "string" ? entry.seriesId : "";
    const unit = units.get(entry.seriesName);
    const summary = readSummary(entry.data);
    // A recorded value keeps its digits; a mean has none of its own to keep.
    const formattedValue = unit && !summary ? numberFormatter.format(value[1]) : formatNumber(value[1]);
    const forecast = seriesId.startsWith("forecast:") ? forecastIntervalText(entry.value, formatNumber) : "";
    const peak = readPeakCount(entry.data);
    lines.push(`${entry.seriesName}: ${formattedValue}${unit ? ` ${unit}` : ""}${summary || means?.has(seriesId) ? " (mean)" : ""}${peak > 1 ? ` (highest of ${peak})` : ""}${forecast}`);
    if (summary) lines.push(`Min–max: ${formatRange(summary.minimum!, summary.maximum!)}${unit ? ` ${unit}` : ""} · ${summary.count} readings`);
    const observation = readObservationDetails(entry.data);
    if (observation) {
      lines.push(`Alarm threshold: ${observation.threshold !== null ? formatNumber(observation.threshold) : "unavailable"}`);
      lines.push(`Alarm: ${alarmText(observation)}`);
    }
  }
  return lines.join("\n");
};

export const buildTelemetryChartOption = ({
  model, valueType = "number", ...options
}: BuildTelemetryChartOptionInput): TelemetryChartOption => buildMonitoringChartOption({
  ...options,
  model: { readings: [{ ...model.telemetry, valueType, pendingTelemetry: model.pendingTelemetry,
    anomalyMarkers: model.anomalyMarkers }], detectorInputs: model.detectorInputs, secondarySeries: model.secondarySeries,
    range: model.range, extent: model.extent },
});

/** The padded ends of a detection pane are room around its values, not values to read. */
const labelWithin = (bounds: DetectionValueBounds | undefined, format: (value: number) => string) =>
  (value: number): string => bounds && (value <= bounds.minimum || value >= bounds.maximum) ? "" : format(Number(value));

type Plotted = readonly [time: number, value: number | null, ...rest: unknown[]];
/**
 * Values with no line to either side, such as one sample between two pauses. A line
 * draws nothing for one, so it gets a dot. A reading or input line shows a single value
 * itself; a score line never draws a symbol, so `single` gives its only result a dot too.
 */
const loneDots = (id: string, name: string, points: readonly Plotted[], color: string, axis: number, size: number,
  single = false): ScatterSeriesOption[] => {
  const data = points.length < 2 && !single ? [] : points.flatMap(([time, value], index) =>
    value !== null && (points[index - 1]?.[1] ?? null) === null && (points[index + 1]?.[1] ?? null) === null ? [[time, value]] : []);
  return data.length ? [{ id: `history-dot:${id}`, name, type: "scatter", xAxisIndex: axis, yAxisIndex: axis, data,
    symbolSize: size, itemStyle: { color }, silent: true, emphasis: { disabled: true }, tooltip: { show: false },
    animation: false, z: 3 }] : [];
};

/** Zero when the values are non-negative and the padded scale would dip below it; otherwise the automatic minimum. */
const nonNegativeFloor = ({ min, max }: { min: number; max: number }): number =>
  (min >= 0 && min - (max - min) * 0.1 < 0 ? 0 : null) as number;

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
  const detectorInputs = model.detectorInputs ?? [];
  const panes = [
    ...model.readings.map(reading => reading.id),
    ...(detectorInputs.length ? ["inputs"] : []),
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
        top: index === 0 ? 26 : 242 + (index - 1) * 164,
        ...(panes.length === 1 ? { bottom: 76 } : { height: index === 0 ? 164 : 112 }),
      }))
    : panes.length === 1
    ? [{ left: 68, right: 40, top: 58, bottom: 84 }]
    : panes.length === 2
      ? [
          { left: 68, right: 40, top: 58, height: 185 },
          { left: 68, right: 40, top: 290, height: 135 },
        ]
    : panes.map((_, index) => index === 0
        ? { left: 68, right: 40, top: 58, height: 180 }
        : { left: 68, right: 40, top: 288 + (index - 1) * 162, height: 120 });
  const visibleSpan = viewport.mode === "absolute" ? viewport.endMs - viewport.startMs
    : domain ? domain[1] - domain[0] : Infinity;
  const axisLabel = {
    color: colors.mutedForeground,
    fontSize: 12,
    formatter: timeAxisLabelFormatter(timeZone, locale, visibleSpan, !compact),
    rich: { day: { color: colors.foreground, fontSize: 12, fontWeight: 600 } },
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
    // One hairline crosses every pane; only the time axis under the last one names its time.
    axisPointer: { show: true, snap: false, label: { show: index === panes.length - 1,
      ...(compact ? { formatter: (params: { value: number | string | Date }) => formatChartTime(Number(params.value), timeZone, "axis", locale) } : {}) } },
    name:
      !compact && index === panes.length - 1 ? `Local time (${timeZone})` : undefined,
    nameLocation: "middle" as const,
    nameGap: 35,
    nameTextStyle: { color: colors.mutedForeground, fontSize: 12 },
  }));
  const dataZoomRange =
    viewport.mode === "absolute"
      ? { startValue: viewport.startMs, endValue: viewport.endMs }
      : domain
        ? { startValue: domain[0], endValue: domain[1] }
        : { start: 0, end: 100 };

  // Faint dashed rules at each local midnight, beside the dated tick labels.
  const dayBreaks = (domain ? localMidnights(domain[0], domain[1], timeZone) : []).map(time => ({ xAxis: time,
    lineStyle: { color: colors.mutedForeground, type: "dashed" as const, width: 1, opacity: 0.35 } }));
  const dayBreakLine = { silent: true, animation: false, symbol: ["none", "none"], label: { show: false }, z: 1,
    data: dayBreaks };

  const alarmColor = colors.alarmBoundary ?? "#dc2626";
  // How far from the pointer each series still speaks: see `formatTelemetryTooltip`.
  const reach = new Map<string, number>();
  const means = new Set<string>();
  const valueTimes = (points: readonly Plotted[]) => points.flatMap(([time, value]) => value === null ? [] : [time]);
  const historyBands: LineSeriesOption[] = [];
  const dots: ScatterSeriesOption[] = [];
  // Alarm episodes the width cannot separate, such as an alarm flapping around its threshold, read as one.
  const joinWithin = Number.isFinite(visibleSpan) ? visibleSpan / 150 : 0;
  const telemetrySeries: LineSeriesOption[] = model.readings.map((reading, index) => {
    const valueType = reading.valueType ?? "number";
    const telemetryValueExtent = reading.data.reduce<[number, number] | undefined>((extent, [, value]) =>
      extent ? [Math.min(extent[0], value), Math.max(extent[1], value)] : [value, value], undefined);
    const display = reading.presentation && historyChartData(reading.presentation);
    if (display) historyBands.push(...historyBandSeries(reading.id, display, reading.color, index));
    dots.push(...loneDots(reading.id, reading.name, display?.map(point => point.value) ?? reading.data, reading.color, index, 5));
    // A mean speaks for its own interval; a recorded sample as far as its line would bridge.
    reach.set(reading.id, reading.presentation?.representation === "mean" ? reading.presentation.interval_ms
      : getPauseLimit(valueTimes(display?.map(point => point.value) ?? reading.data)));
    // Consecutive alarm results are one episode: a soft band from its first to its last
    // result, and a line where it began. A single result is that line alone.
    const alarmSpans = (reading.alarmSpans ?? []).reduce<Array<[number, number]>>((joined, [start, end]) => {
      const last = joined[joined.length - 1];
      if (last && start - last[1] <= joinWithin) last[1] = Math.max(last[1], end);
      else joined.push([start, end]);
      return joined;
    }, []);
    const episodes = alarmSpans.filter(([start, end]) => end > start);
    return {
      id: reading.id,
      name: reading.name,
      type: "line",
      xAxisIndex: index,
      yAxisIndex: index,
      data: display?.map(point => point.summary ? point : point.value) ?? reading.data,
      smooth: false,
      step: valueType === "boolean" ? "end" : false,
      showSymbol: (display?.length ?? reading.data.length) === 1,
      symbolSize: 5,
      sampling: valueType === "number" && !display ? "lttb" : "none",
      connectNulls: false,
      lineStyle: { color: reading.color, width: 2.25 },
      itemStyle: { color: reading.color },
      emphasis: { disabled: true },
      animation: false,
      z: 3,
      markPoint: {
        symbol: "circle",
        label: { show: false },
        data: buildTelemetryEventMarkPoints(reading.anomalyMarkers, {
          timeZone, locale, colors,
          extent: viewport.mode === "absolute" ? [viewport.startMs, viewport.endMs] : domain,
          unit: reading.unit, telemetryValueExtent,
        }),
      },
      ...(episodes.length ? { markArea: { silent: true, animation: false, label: { show: false },
        itemStyle: { color: colors.alarmFill ?? "rgba(220, 38, 38, 0.12)" },
        data: episodes.map(([start, end]) => [{ xAxis: start }, { xAxis: end }]) } } : {}),
      ...(alarmSpans.length || dayBreaks.length ? { markLine: { ...dayBreakLine,
        lineStyle: { color: alarmColor, width: 1, opacity: 0.55 },
        data: [...alarmSpans.map(([start]) => ({ xAxis: start })), ...dayBreaks],
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

  const inputsPane = panes.indexOf("inputs");
  const palette = colors.seriesPalette?.length ? colors.seriesPalette : DEFAULT_SERIES_PALETTE;
  detectorInputs.forEach((series, index) => {
    const forecastId = `forecast:${series.id.slice("input:".length)}`;
    reach.set(series.id, getPauseLimit(valueTimes(series.data)));
    if (series.forecast) reach.set(forecastId, getPauseLimit(valueTimes(series.forecast)));
    if (series.range) means.add(series.id).add(forecastId);
    dots.push(...loneDots(series.id, series.name, series.data, palette[index % palette.length]!, inputsPane, 4));
  });
  // The range a feature covered within each interval. Beside a forecast it shows what a
  // mean alone would hide: values that left the forecast interval.
  const inputBands: LineSeriesOption[] = detectorInputs.flatMap((series, index) => series.range
    ? bandSeries(series.id, series.range, palette[index % palette.length]!, inputsPane, .1) : []);
  const inputSeries: LineSeriesOption[] = detectorInputs.map((series, index) => ({
    id: series.id,
    name: series.name,
    type: "line",
    xAxisIndex: inputsPane,
    yAxisIndex: inputsPane,
    data: series.data,
    showSymbol: series.data.length === 1,
    symbolSize: 4,
    connectNulls: false,
    lineStyle: { color: palette[index % palette.length], width: 1.5 },
    itemStyle: { color: palette[index % palette.length] },
    emphasis: { disabled: true },
    animation: false,
    ...(index === 0 && dayBreaks.length ? { markLine: dayBreakLine } : {}),
  }));
  // What a forecaster step expected of its feature: a dashed line in the feature's colour,
  // and the interval around it as a band. The band is two stacked lines, the lower bound
  // and the width above it, so only the space between the bounds is filled.
  const forecastSeries: LineSeriesOption[] = detectorInputs.flatMap((series, index) => {
    const forecast = series.forecast;
    if (!forecast?.length) return [];
    const key = series.id.slice("input:".length);
    const color = palette[index % palette.length];
    const bound = {
      type: "line" as const,
      xAxisIndex: inputsPane,
      yAxisIndex: inputsPane,
      stack: `forecast-band:${key}`,
      stackStrategy: "all" as const,
      showSymbol: false,
      connectNulls: false,
      silent: true,
      lineStyle: { opacity: 0 },
      emphasis: { disabled: true },
      animation: false,
    };
    return [
      {
        id: `forecast:${key}`,
        name: `${series.name} forecast`,
        type: "line",
        xAxisIndex: inputsPane,
        yAxisIndex: inputsPane,
        data: forecast,
        encode: { x: 0, y: 1 },
        showSymbol: forecast.length === 1,
        symbolSize: 4,
        connectNulls: false,
        lineStyle: { color, width: 1, type: "dashed" },
        itemStyle: { color },
        emphasis: { disabled: true },
        animation: false,
      },
      ...(forecast.some(([, , lower]) => lower !== null) ? [
        { ...bound, id: `forecast-band:${key}:lower`, data: forecast.map(([time, , lower]) => [time, lower]) },
        { ...bound, id: `forecast-band:${key}:width`, areaStyle: { color, opacity: 0.15 },
          data: forecast.map(([time, , lower, upper]) => [time, lower === null || upper === null ? null : upper - lower]) },
      ] : []),
    ];
  });
  const inputsLegend: LegendComponentOption | undefined = detectorInputs.length && compact ? {
    id: "detector-inputs-legend",
    type: "scroll",
    data: detectorInputs.map(series => series.name),
    top: Number(grid[inputsPane]?.top ?? 0) - 22,
    right: monitoring ? 18 : 16,
    width: "60%",
    icon: "roundRect",
    itemWidth: 12,
    itemHeight: 3,
    textStyle: { color: colors.foreground, fontSize: 11 },
    pageTextStyle: { color: colors.mutedForeground },
  } : undefined;

  const ruledPanes = new Set<number>();
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
    reach.set(series.id, getPauseLimit(series.data.flatMap(point => point.observation ? [point.value[0]] : [])));
    dots.push(...loneDots(series.id, series.name, series.data.map(point => point.value), colors.primary, paneIndex, 5, true));
    if (dayBreaks.length && !ruledPanes.has(paneIndex)) {
      ruledPanes.add(paneIndex);
      line.markLine = dayBreakLine;
    }
    if (!monitoring) return [line];
    // A dot where an alarm begins; the results that keep it up already sit above the threshold.
    let alarmed = false;
    const onsets = series.data.flatMap(point => {
      if (!point.observation) return [];
      const began = Boolean(point.observation.alarmFired) && !alarmed;
      alarmed = Boolean(point.observation.alarmFired);
      return began && point.value[1] !== null ? [{
        name: "Alarm decision", coord: [point.value[0], point.value[1]], symbol: "circle", symbolSize: 6,
        itemStyle: { color: alarmColor },
      }] : [];
    });
    // An alarm a Mute alarms step held back: the same dot, left open over the line.
    const muted = series.data.flatMap(point => point.observation?.alarmMuted && point.value[1] !== null ? [{
      name: "Muted alarm", coord: [point.value[0], point.value[1]], symbol: "circle", symbolSize: 6,
      itemStyle: { color: colors.popover, borderColor: alarmColor, borderWidth: 1 },
    }] : []);
    line.markPoint = { ...line.markPoint, data: [...(line.markPoint?.data ?? []), ...onsets, ...muted] };
    return [line, buildThresholdSeriesOption(series, paneIndex, alarmColor)];
  });

  return {
    backgroundColor: "transparent",
    animation: false,
    aria: { enabled: true, description: accessibleDescription },
    color: [...model.readings.map(reading => reading.color), colors.primary],
    grid: grid.map((pane) => ({ ...pane, outerBoundsMode: "none" })),
    legend: compact ? inputsLegend ?? { show: false } : {
      id: "telemetry-legend",
      type: "scroll",
      top: 10,
      left: 18,
      right: 18,
      textStyle: { color: colors.foreground, fontSize: 12 },
      pageTextStyle: { color: colors.mutedForeground },
    },
    axisPointer: {
      link: [{ xAxisIndex: "all" }],
      lineStyle: { color: colors.mutedForeground, type: "solid", width: 1, opacity: 0.55 },
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
      axisPointer: { type: "line" },
      formatter: (params: unknown) =>
        (monitoring ? formatMonitoringObservationTooltip(params, model.readings,
          time => formatChartTime(time, timeZone, "tooltip", locale), formatNumber) : undefined)
          ?? formatTelemetryTooltip(params, timeZone, units, locale, reach, means),
    },
    xAxis,
    yAxis: [
      ...model.readings.map((reading, index) => ({
        id: `${reading.id}-values`,
        type: "value" as const,
        scale: true,
        boundaryGap: ["10%", "10%"] as [string, string],
        // The breathing room under the lowest value must not invent a negative scale.
        min: nonNegativeFloor,
        ...(reading.valueType === "boolean" ? { scale: false, min: 0, max: 1, interval: 1 } : {}),
        ...(compact ? { splitNumber: 4 } : {}),
        gridIndex: index,
        ...(compact && !monitoring ? { nameGap: 10 } : {}),
        name: compact && !monitoring ? reading.unit : reading.unit
          ? `${reading.name} (${reading.unit})` : reading.name,
        nameTextStyle: { color: monitoring ? reading.color : colors.mutedForeground, fontSize: 12, align: "left" as const,
          ...(monitoring ? { overflow: "truncate" as const, width: 220 } : {}) },
        axisLabel: { color: colors.mutedForeground, fontSize: 12 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: colors.border, type: "dashed" as const } },
      })),
      ...(detectorInputs.length
        ? [
            {
              id: "detector-input-values",
              type: "value" as const,
              scale: true,
              boundaryGap: ["10%", "10%"] as [string, string],
              min: nonNegativeFloor,
              ...(compact ? { splitNumber: 3 } : {}),
              gridIndex: inputsPane,
              name: "Detector inputs",
              nameTextStyle: { color: colors.mutedForeground, fontSize: 12, align: "left" as const },
              axisLabel: { color: colors.mutedForeground, fontSize: 12,
                formatter: (value: number) => formatNumber(Number(value)), hideOverlap: true },
              axisLine: { show: false },
              axisTick: { show: false },
              splitLine: { lineStyle: { color: colors.border, type: "dashed" as const } },
            },
          ]
        : []),
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
              nameTextStyle: { color: colors.mutedForeground, fontSize: 12, align: "left" as const },
              axisLabel: {
                color: colors.mutedForeground,
                fontSize: 12,
                formatter: labelWithin(boundsByPane.get("static"), (value) => value.toPrecision(2)),
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
              nameTextStyle: { color: colors.mutedForeground, fontSize: 12, align: "left" as const },
              axisLabel: { color: colors.mutedForeground, fontSize: 12,
                formatter: labelWithin(boundsByPane.get("adaptive"), formatNumber), hideOverlap: true },
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
      ...historyBands,
      ...pendingTelemetrySeries,
      ...inputBands,
      ...inputSeries,
      ...forecastSeries,
      ...secondarySeries,
      ...dots,
    ],
  };
};
