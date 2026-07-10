/**
 * Anomaly processing utilities for matching anomalies with telemetry data
 * and creating visual overlays
 */

import { groupTimestampsIntoRanges, timestampsAreClose } from './time-utils';
import { INTERVALS } from './constants';
import type { Anomaly } from '@/types/charger';
import {
  formatAnomalyValue,
  getAnomalyValueLabel,
} from '@/lib/anomaly-semantics';

export type { Anomaly };
export const MULTIVARIATE_TELEMETRY_TYPE = "__multivariate__";

export interface RedZone {
  start: string;
  end: string;
  anomalies: Anomaly[];
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

const ANOMALY_STYLES: Record<
  string,
  { color: string; radius: number; opacity: number }
> = {
  threshold_exceeded: { color: "#ef4444", radius: 3, opacity: 0.8 },
  spike: { color: "#f97316", radius: 4, opacity: 0.9 },
  drop: { color: "#3b82f6", radius: 4, opacity: 0.9 },
  pattern_break: { color: "#8b5cf6", radius: 3, opacity: 0.7 },
  ml_conformal_static_univariate: { color: "#dc2626", radius: 5, opacity: 0.95 },
  ml_conformal_static_multivariate: { color: "#991b1b", radius: 6, opacity: 0.95 },
  ml_tailprob_univariate: { color: "#ea580c", radius: 4, opacity: 0.9 },
  ml_tailprob_multivariate: { color: "#c2410c", radius: 5, opacity: 0.9 },
  default: { color: "#dc2626", radius: 3, opacity: 0.8 },
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

  // Keep the original strings because Recharts uses timestamp values as
  // categorical coordinates. Equivalent normalized strings (for example,
  // \`...00Z\` and \`...00.000Z\`) are not interchangeable on that axis.
  const timestamps = validAnomalies.map(({ anomaly }) => anomaly.timestamp);

  // Group into continuous ranges
  const ranges = groupTimestampsIntoRanges(
    timestamps,
    INTERVALS.ANOMALY_ZONE_GAP,
    true
  );

  const zones: RedZone[] = [];
  let anomalyIndex = 0;

  for (const range of ranges) {
    const zoneAnomalies: Anomaly[] = [];
    const startTime = new Date(range.start).getTime();
    const endTime = new Date(range.end).getTime();

    while (
      anomalyIndex < validAnomalies.length &&
      validAnomalies[anomalyIndex].timestampMs < startTime
    ) {
      anomalyIndex += 1;
    }

    while (
      anomalyIndex < validAnomalies.length &&
      validAnomalies[anomalyIndex].timestampMs <= endTime
    ) {
      const { anomaly } = validAnomalies[anomalyIndex];
      zoneAnomalies.push(anomaly);
      anomalyIndex += 1;
    }

    zones.push({
      start: range.start,
      end: range.end,
      anomalies: zoneAnomalies,
    });
  }

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
export const getAnomalyStyle = (anomalyType: string) => {
  return ANOMALY_STYLES[anomalyType] || ANOMALY_STYLES.default;
};
