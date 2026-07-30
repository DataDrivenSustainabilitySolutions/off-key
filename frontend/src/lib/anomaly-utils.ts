/**
 * Anomaly processing utilities for matching anomalies with telemetry data
 * and creating visual overlays
 */

import { timestampsAreClose } from './time-utils';
import { INTERVALS } from './constants';
import type { Anomaly, TelemetryDataPoint } from '@/types/charger';
import {
  formatAnomalyValue,
  getAnomalyValueLabel,
} from '@/lib/anomaly-semantics';

export type { Anomaly };
export const MULTIVARIATE_TELEMETRY_TYPE = "__multivariate__";

export interface RedZone {
  startMs: number;
  endMs: number;
  anomalies: Anomaly[];
}

export interface AnomalyMarker extends TelemetryDataPoint {
  time: number;
  anomaly: Anomaly;
  style: AnomalyStyle;
}

const ISO_TIMESTAMP_REGEX = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/u;

export const formatAnomalySensorSet = (
  sensorSet: Anomaly["sensor_set"]
): string => {
  return sensorSet && sensorSet.length > 0 ? sensorSet.join(", ") : "not recorded";
};

const multivariateAnomalyAppliesToTelemetry = (
  anomaly: Anomaly,
  telemetryType: string
): boolean => {
  if (anomaly.telemetry_type !== MULTIVARIATE_TELEMETRY_TYPE) {
    return false;
  }

  // Legacy multivariate anomalies without sensor_set metadata are shown on all charts.
  if (!anomaly.sensor_set || anomaly.sensor_set.length === 0) {
    return true;
  }

  return anomaly.sensor_set.includes(telemetryType);
};

interface AnomalyStyle {
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
 * Create red zones from anomaly clusters
 * Groups nearby anomalies into continuous visual zones
 */
export const createAnomalyZones = (
  anomalies: Anomaly[]
): RedZone[] => {
  if (anomalies.length === 0) return [];

  const parseIsoTimestamp = (value: string): number | null => {
    if (!ISO_TIMESTAMP_REGEX.test(value)) {
      return null;
    }
    const timestampMs = Date.parse(value);
    return Number.isFinite(timestampMs) ? timestampMs : null;
  };

  const validAnomalies = anomalies
    .map(anomaly => {
      const timestampMs = parseIsoTimestamp(anomaly.timestamp);
      if (timestampMs === null) {
        return null;
      }
      return { anomaly, timestampMs };
    })
    .filter((item): item is { anomaly: Anomaly; timestampMs: number } => item !== null)
    .sort((left, right) => left.timestampMs - right.timestampMs);

  if (validAnomalies.length === 0) return [];

  const zones: RedZone[] = [];
  const first = validAnomalies[0];
  if (!first) return zones;

  let currentZone: RedZone = {
    startMs: first.timestampMs,
    endMs: first.timestampMs,
    anomalies: [first.anomaly],
  };
  for (const current of validAnomalies.slice(1)) {
    if (current.timestampMs - currentZone.endMs <= INTERVALS.ANOMALY_ZONE_GAP) {
      currentZone.endMs = current.timestampMs;
      currentZone.anomalies.push(current.anomaly);
      continue;
    }
    zones.push(currentZone);
    currentZone = {
      startMs: current.timestampMs,
      endMs: current.timestampMs,
      anomalies: [current.anomaly],
    };
  }
  zones.push(currentZone);

  return zones;
};

/**
 * Check if a telemetry point has an associated anomaly
 * Returns the anomaly if found, null otherwise
 */
export const hasAnomaly = (
  timestamp: string,
  anomalies: Anomaly[]
): Anomaly | null => {
  return anomalies.find(anomaly =>
    timestampsAreClose(timestamp, anomaly.timestamp, 5 * INTERVALS.POLLING) // 5 second tolerance
  ) || null;
};

/**
 * Match telemetry points to anomalies once, before the chart option is built.
 */
export const createAnomalyMarkers = (
  telemetry: TelemetryDataPoint[],
  anomalies: Anomaly[],
  toleranceMs: number = 5 * INTERVALS.POLLING
): AnomalyMarker[] => {
  if (telemetry.length === 0 || anomalies.length === 0 || toleranceMs < 0) {
    return [];
  }

  const bucketSize = Math.max(toleranceMs, 1);
  const buckets = new Map<number, Array<{ anomaly: Anomaly; index: number; time: number }>>();

  anomalies.forEach((anomaly, index) => {
    const time = Date.parse(anomaly.timestamp);
    if (!Number.isFinite(time)) return;
    const bucket = Math.floor(time / bucketSize);
    const entries = buckets.get(bucket) ?? [];
    entries.push({ anomaly, index, time });
    buckets.set(bucket, entries);
  });

  return telemetry.flatMap((point) => {
    const time = Date.parse(point.timestamp);
    if (!Number.isFinite(time)) return [];

    let match: { anomaly: Anomaly; index: number } | undefined;
    const firstBucket = Math.floor((time - toleranceMs) / bucketSize);
    const lastBucket = Math.floor((time + toleranceMs) / bucketSize);
    for (let bucket = firstBucket; bucket <= lastBucket; bucket += 1) {
      for (const candidate of buckets.get(bucket) ?? []) {
        if (
          Math.abs(time - candidate.time) <= toleranceMs &&
          (match === undefined || candidate.index < match.index)
        ) {
          match = candidate;
        }
      }
    }

    return match
      ? [{
          ...point,
          time,
          anomaly: match.anomaly,
          style: getAnomalyStyle(match.anomaly.anomaly_type),
        }]
      : [];
  });
};

/**
 * Filter anomalies by telemetry type and time range
 */
export const filterAnomalies = (
  anomalies: Anomaly[],
  telemetryType: string,
  fromDate?: Date,
  toDate?: Date
): Anomaly[] => {
  return anomalies.filter(anomaly => {
    // Filter by telemetry type
    if (
      anomaly.telemetry_type !== telemetryType &&
      !multivariateAnomalyAppliesToTelemetry(anomaly, telemetryType)
    ) {
      return false;
    }

    // Filter by time range if provided
    if (fromDate || toDate) {
      const anomalyTime = new Date(anomaly.timestamp).getTime();
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
 * Create tooltip content for anomaly visualization
 */
export const createAnomalyTooltip = (anomaly: Anomaly): string => {
  const formattedTime = new Date(anomaly.timestamp).toLocaleString();
  const valueLabel = getAnomalyValueLabel(anomaly.value_type);
  const formattedValue = formatAnomalyValue(
    anomaly.anomaly_value,
    anomaly.value_type
  );
  return `Anomaly: ${anomaly.anomaly_type}
${valueLabel}: ${formattedValue}
Time: ${formattedTime}
Type: ${anomaly.telemetry_type}
Sensors: ${formatAnomalySensorSet(anomaly.sensor_set)}`;
};

/**
 * Determine the visual style for an anomaly based on its type
 */
export const getAnomalyStyle = (anomalyType: string): AnomalyStyle =>
  ANOMALY_STYLES[anomalyType] ?? DEFAULT_ANOMALY_STYLE;
