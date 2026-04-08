/**
 * Time-related utilities for handling timestamps and date ranges
 */

import { INTERVALS } from './constants';

export interface TelemetryPoint {
  timestamp: string;
  value: number;
}

/**
 * Check if a timestamp falls within a date range
 */
export const isWithinTimeRange = (
  timestamp: string,
  from?: Date,
  to?: Date
): boolean => {
  const time = new Date(timestamp).getTime();
  const fromTime = from?.getTime() ?? -Infinity;
  const toTime = to?.getTime() ?? Infinity;
  return time >= fromTime && time <= toTime;
};

/**
 * Find the telemetry point closest to an anomaly timestamp
 * Used for precise anomaly-to-telemetry matching
 */
export const findNearestTelemetryPoint = (
  anomalyTimestamp: string,
  telemetryData: TelemetryPoint[],
  maxDiffMs: number = INTERVALS.REAL_TIME_UPDATE // 1 minute tolerance
): TelemetryPoint | null => {
  if (telemetryData.length === 0) return null;

  const anomalyTime = new Date(anomalyTimestamp).getTime();
  let closestPoint: TelemetryPoint | null = null;
  let minDiff = Infinity;

  for (const point of telemetryData) {
    const pointTime = new Date(point.timestamp).getTime();
    const diff = Math.abs(anomalyTime - pointTime);

    if (diff < minDiff && diff <= maxDiffMs) {
      minDiff = diff;
      closestPoint = point;
    }
  }

  return closestPoint;
};

/**
 * Group timestamps into continuous ranges
 * Used for creating red zones from anomaly clusters
 */
export const groupTimestampsIntoRanges = (
  timestamps: string[],
  maxGapMs: number = 5 * INTERVALS.REAL_TIME_UPDATE // 5 minutes max gap
): Array<{ start: string; end: string }> => {
  if (timestamps.length === 0) return [];

  // Sort timestamps chronologically
  const sorted = [...timestamps].sort((a, b) =>
    new Date(a).getTime() - new Date(b).getTime()
  );

  const ranges: Array<{ start: string; end: string }> = [];
  let currentStart = sorted[0];
  let currentEnd = sorted[0];

  for (let i = 1; i < sorted.length; i++) {
    const currentTime = new Date(sorted[i]).getTime();
    const lastTime = new Date(currentEnd).getTime();

    if (currentTime - lastTime <= maxGapMs) {
      // Extend current range
      currentEnd = sorted[i];
    } else {
      // Start new range
      ranges.push({ start: currentStart, end: currentEnd });
      currentStart = sorted[i];
      currentEnd = sorted[i];
    }
  }

  // Add the last range
  ranges.push({ start: currentStart, end: currentEnd });

  return ranges;
};

/**
 * Parse and format timestamps consistently
 */
export const formatTimestamp = (timestamp: string, format: 'short' | 'long' = 'short'): string => {
  const date = new Date(timestamp);

  if (format === 'short') {
    const day = String(date.getDate()).padStart(2, '0');
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const hour = String(date.getHours()).padStart(2, '0');
    const minute = String(date.getMinutes()).padStart(2, '0');
    const second = String(date.getSeconds()).padStart(2, '0');
    return `${day}.${month}, ${hour}:${minute}:${second}`;
  }

  return date.toLocaleString('en-US', {
    dateStyle: 'short',
    timeStyle: 'medium',
  });
};

/**
 * Format charger last-seen values safely.
 * Returns "Never" when no valid timestamp exists.
 */
export const formatLastSeen = (timestamp?: string | null): string => {
  if (!timestamp) {
    return "Never";
  }

  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return "Never";
  }

  return date.toLocaleString();
};

/**
 * Check if two timestamps are approximately equal
 * Useful for matching anomalies with telemetry points
 */
export const timestampsAreClose = (
  timestamp1: string,
  timestamp2: string,
  toleranceMs: number = INTERVALS.POLLING // 1 second tolerance
): boolean => {
  const time1 = new Date(timestamp1).getTime();
  const time2 = new Date(timestamp2).getTime();
  return Math.abs(time1 - time2) <= toleranceMs;
};
