import type { MarkPointComponentOption } from "echarts/components";

import { formatAnomalyValue, getAnomalyValueLabel } from "@/lib/anomaly-semantics";
import {
  MULTIVARIATE_TELEMETRY_TYPE,
  type AnomalyMarker,
  type AnomalySample,
} from "@/lib/anomaly-utils";

export interface TelemetryEventGroup {
  timeMs: number;
  events: AnomalyMarker[];
  sample?: AnomalySample;
}

export const groupTelemetryEvents = (
  markers: readonly AnomalyMarker[],
): TelemetryEventGroup[] => {
  const groups = new Map<number, TelemetryEventGroup>();
  markers.forEach((marker) => {
    if (!Number.isFinite(marker.time)) return;
    const group = groups.get(marker.time) ?? { timeMs: marker.time, events: [] };
    group.events.push(marker);
    if (marker.sample) group.sample = marker.sample;
    groups.set(marker.time, group);
  });
  return [...groups.values()].sort((left, right) => left.timeMs - right.timeMs);
};

interface TelemetryEventDisplayOptions {
  timeZone: string;
  locale?: string;
  unit?: string;
  telemetryValueExtent?: readonly [minimum: number, maximum: number];
}

const getContextualSampleEdge = (
  group: TelemetryEventGroup,
  extent: TelemetryEventDisplayOptions["telemetryValueExtent"],
): "upper" | "lower" | undefined => {
  if (!group.sample || !extent || !Number.isFinite(extent[0]) || !Number.isFinite(extent[1]) || extent[0] > extent[1]) {
    return undefined;
  }
  if (group.sample.value > extent[1]) return "upper";
  if (group.sample.value < extent[0]) return "lower";
  return undefined;
};

const eventTimeFormatters = new Map<string, Intl.DateTimeFormat>();

export const formatTelemetryEventTime = (timeMs: number, timeZone: string, locale?: string): string => {
  const key = `${timeZone}\u0000${locale ?? "default"}`;
  let formatter = eventTimeFormatters.get(key);
  if (!formatter) {
    const options: Intl.DateTimeFormatOptions & { fractionalSecondDigits: 3 } = {
      timeZone, year: "numeric", month: "short", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
      fractionalSecondDigits: 3, timeZoneName: "short",
    };
    formatter = new Intl.DateTimeFormat(locale, options);
    eventTimeFormatters.set(key, formatter);
  }
  return formatter.format(timeMs);
};

export const formatEventSampleOffset = (offsetMs: number): string => {
  if (offsetMs === 0) return "0 ms (same timestamp)";
  const sign = offsetMs > 0 ? "+" : "−";
  const value = Math.abs(offsetMs) < 1_000
    ? `${Math.abs(offsetMs)} ms`
    : `${Math.abs(offsetMs) / 1_000} s`;
  return `${sign}${value} (sample ${offsetMs > 0 ? "after" : "before"} event)`;
};

export const formatTelemetryEventTooltip = (
  group: TelemetryEventGroup,
  { timeZone, locale, unit, telemetryValueExtent }: TelemetryEventDisplayOptions,
): string => {
  const formatTime = (time: number) => formatTelemetryEventTime(time, timeZone, locale);
  const lines = [
    `${group.events.length} anomaly event${group.events.length === 1 ? "" : "s"}`,
    `Anomaly recorded at: ${formatTime(group.timeMs)}`,
  ];
  group.events.forEach(({ anomaly }) => {
    lines.push(
      `Event ${anomaly.anomaly_id}: ${anomaly.anomaly_type.replace(/_/gu, " ")}`,
      `${getAnomalyValueLabel(anomaly.value_type)}: ${formatAnomalyValue(anomaly.anomaly_value, anomaly.value_type)}`,
      `Sensors: ${anomaly.sensor_set?.join(", ") || (anomaly.telemetry_type === MULTIVARIATE_TELEMETRY_TYPE ? "not recorded" : anomaly.telemetry_type)}`,
    );
  });
  if (group.sample) {
    const numberFormatter = new Intl.NumberFormat(locale, { maximumFractionDigits: 6 });
    lines.push(
      `Nearest telemetry sample at: ${formatTime(group.sample.time)}`,
      `Telemetry value: ${numberFormatter.format(group.sample.value)}${unit ? ` ${unit}` : ""}`,
      `Sample offset: ${formatEventSampleOffset(group.sample.time - group.timeMs)}`,
    );
    const sampleEdge = getContextualSampleEdge(group, telemetryValueExtent);
    if (sampleEdge) {
      lines.push(`Contextual sample is ${sampleEdge === "upper" ? "above" : "below"} the displayed telemetry range.`);
    }
    if (group.events.some(({ anomaly }) =>
      anomaly.telemetry_type === MULTIVARIATE_TELEMETRY_TYPE || (anomaly.sensor_set?.length ?? 0) > 1,
    )) {
      lines.push("Nearby sensor context; exact detector input is not recorded with the event.");
    }
  } else {
    lines.push("No nearby telemetry sample.");
  }
  return lines.join("\n");
};

interface TelemetryEventMarkPointOptions extends TelemetryEventDisplayOptions {
  colors: { foreground: string; mutedForeground: string; popover: string };
  extent?: readonly [number, number];
}

type EventMarkPoint = NonNullable<MarkPointComponentOption["data"]>[number] & {
  tooltip: { trigger: "item"; formatter: () => string };
};

export const buildTelemetryEventMarkPoints = (
  groups: readonly TelemetryEventGroup[],
  options: TelemetryEventMarkPointOptions,
): EventMarkPoint[] => groups
  .filter((group) => group.events.length > 0 && (!options.extent || (
    group.timeMs >= options.extent[0] && group.timeMs <= options.extent[1]
  )))
  .map((group) => {
    const { style } = group.events[0]!;
    const matched = group.sample !== undefined;
    const sampleEdge = getContextualSampleEdge(group, options.telemetryValueExtent);
    const edge = matched ? sampleEdge : "upper";
    return {
      name: `${group.events.length} anomaly event${group.events.length === 1 ? "" : "s"}`,
      coord: [group.timeMs, group.sample?.value ?? 0],
      symbol: matched ? "circle" : "triangle",
      symbolSize: Math.max(style.radius * 2, 9),
      ...(edge ? {
        relativeTo: "coordinate" as const,
        y: edge === "upper" ? "0%" : "100%",
        symbolOffset: [0, edge === "upper" ? 6 : -6],
      } : {}),
      ...(!matched ? { symbolRotate: 180 } : {}),
      itemStyle: {
        color: style.color,
        borderColor: options.colors.foreground,
        borderWidth: 1,
        opacity: style.opacity,
      },
      label: {
        show: group.events.length > 1,
        formatter: String(group.events.length),
        position: "top" as const,
        distance: 3,
        color: options.colors.foreground,
        backgroundColor: options.colors.popover,
        padding: [1, 3],
        fontSize: 10,
      },
      tooltip: {
        trigger: "item" as const,
        formatter: () => formatTelemetryEventTooltip(group, options),
      },
    };
  });
