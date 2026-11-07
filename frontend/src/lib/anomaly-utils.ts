import { epochMilliseconds } from "@/lib/timestamps";
/**
 * Anomaly processing utilities for matching anomalies with telemetry data
 * and creating visual overlays
 */

import { ANOMALY_SAMPLE_TOLERANCE_MS } from './constants';
import type { Alarm, TelemetryDataPoint } from '@/types/charger';

export interface AnomalySample extends TelemetryDataPoint {
  time: number;
}

export interface AnomalyMarker {
  timestamp: string;
  time: number;
  anomaly: Alarm;
  style: AnomalyStyle;
  sample?: AnomalySample;
  value?: number;
}

/** The names of an alarm's readings, or that the monitor did not record them. */
export const formatAlarmReadings = (alarm: Alarm): string => {
  const names = alarm.reading_ids.map((id) => alarm.reading_labels[id] ?? id);
  return names.length > 0 ? names.join(", ") : "not recorded";
};

/** A multivariate alarm about several readings is context on each one's chart. */
export const isAlarmContext = (alarm: Alarm): boolean =>
  alarm.multivariate || alarm.reading_ids.length > 1;

/**
 * Whether an alarm belongs on one reading's chart. A multivariate alarm that
 * did not record its readings belongs on every chart of its device.
 */
const alarmAppliesToReading = (alarm: Alarm, readingId: string): boolean =>
  alarm.reading_ids.includes(readingId) || (alarm.multivariate && alarm.reading_ids.length === 0);

export interface AnomalyStyle {
  color: string;
  radius: number;
  opacity: number;
}

const DEFAULT_ANOMALY_STYLE: AnomalyStyle = {
  color: "#dc2626",
  radius: 3,
  opacity: 0.8,
};

const ANOMALY_STYLES: Record<string, AnomalyStyle> = {
  threshold_exceeded: { color: "#ef4444", radius: 3, opacity: 0.8 },
  spike: { color: "#f97316", radius: 4, opacity: 0.9 },
  drop: { color: "#3b82f6", radius: 4, opacity: 0.9 },
  pattern_break: { color: "#8b5cf6", radius: 3, opacity: 0.7 },
  ml_conformal_static_univariate: { color: "#dc2626", radius: 5, opacity: 0.95 },
  ml_conformal_static_multivariate: { color: "#991b1b", radius: 6, opacity: 0.95 },
  ml_tailprob_univariate: { color: "#ea580c", radius: 4, opacity: 0.9 },
  ml_tailprob_multivariate: { color: "#c2410c", radius: 5, opacity: 0.9 },
};

/**
 * Preserve each event at its recorded time. A nearby finite sample supplies
 * context, rather than changing the event time or marking all nearby samples.
 */
export const createAnomalyMarkers = (
  telemetry: TelemetryDataPoint[],
  anomalies: Alarm[],
  toleranceMs: number = ANOMALY_SAMPLE_TOLERANCE_MS
): AnomalyMarker[] => {
  if (anomalies.length === 0 || !Number.isFinite(toleranceMs) || toleranceMs < 0) {
    return [];
  }

  const samplesByTime = new Map<number, AnomalySample>();
  telemetry.forEach((point) => {
    const time = epochMilliseconds(point.timestamp);
    if (!Number.isFinite(time) || !Number.isFinite(point.value)) return;
    samplesByTime.set(time, { ...point, time });
  });
  const samples = [...samplesByTime.values()].sort((left, right) => left.time - right.time);

  const eventsByIdentity = new Map<string, { anomaly: Alarm; time: number }>();
  anomalies.forEach((anomaly, index) => {
    const time = epochMilliseconds(anomaly.timestamp);
    if (!Number.isFinite(time)) return;
    const identity = anomaly.alarm_id ? `id:${anomaly.alarm_id}` : `row:${index}`;
    eventsByIdentity.set(identity, { anomaly, time });
  });

  return [...eventsByIdentity.values()]
    .sort((left, right) =>
      left.time - right.time || (left.anomaly.alarm_id ?? "").localeCompare(right.anomaly.alarm_id ?? ""),
    )
    .map(({ anomaly, time }) => {
      let lower = 0;
      let upper = samples.length;
      while (lower < upper) {
        const middle = Math.floor((lower + upper) / 2);
        if (samples[middle]!.time < time) lower = middle + 1;
        else upper = middle;
      }

      const before = samples[lower - 1];
      const after = samples[lower];
      const nearest = before && (!after || time - before.time <= after.time - time)
        ? before
        : after;
      const sample = nearest && Math.abs(nearest.time - time) <= toleranceMs
        ? nearest
        : undefined;

      return {
        timestamp: anomaly.timestamp,
        time,
        anomaly,
        style: getAnomalyStyle(anomaly.alarm_type),
        ...(sample ? { sample, value: sample.value } : {}),
      };
    });
};

/**
 * Filter alarms by catalogue reading and time range
 */
export const filterAnomalies = (
  anomalies: Alarm[],
  readingId: string,
  fromDate?: Date,
  toDate?: Date
): Alarm[] => {
  return anomalies.filter(anomaly => {
    if (!alarmAppliesToReading(anomaly, readingId)) {
      return false;
    }

    // Filter by time range if provided
    if (fromDate || toDate) {
      const anomalyTime = epochMilliseconds(anomaly.timestamp);
      const fromTime = fromDate?.getTime() ?? -Infinity;
      const toTime = toDate?.getTime() ?? Infinity;

      if (anomalyTime < fromTime || anomalyTime > toTime) {
        return false;
      }
    }

    return true;
  });
};

/**
 * Determine the visual style for an anomaly based on its type
 */
export const getAnomalyStyle = (anomalyType: string): AnomalyStyle =>
  ANOMALY_STYLES[anomalyType] ?? DEFAULT_ANOMALY_STYLE;
