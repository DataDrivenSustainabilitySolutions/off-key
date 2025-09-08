/**
 * Anomaly processing utilities for matching anomalies with telemetry data
 * and creating visual overlays
 */

import { groupTimestampsIntoRanges, findNearestTelemetryPoint, timestampsAreClose } from './time-utils';
import { INTERVALS } from './constants';

export interface Anomaly {
  charger_id: string;
  timestamp: string;
  telemetry_type: string;
  anomaly_type: string;
  anomaly_value: number;
}

export interface TelemetryPoint {
  timestamp: string;
  value: number;
}

export interface EnhancedTelemetryPoint extends TelemetryPoint {
  hasAnomaly: boolean;
  anomaly?: Anomaly;
}

export interface RedZone {
  start: string;
  end: string;
  anomalies: Anomaly[];
}

/**
 * Match anomalies to telemetry data points by timestamp
 * Returns enhanced telemetry points with anomaly information
 */
export const matchAnomaliesWithTelemetry = (
  telemetryData: TelemetryPoint[],
  anomalies: Anomaly[]
): EnhancedTelemetryPoint[] => {
  return telemetryData.map(point => {
    // Find anomaly that matches this telemetry point's timestamp
    const matchingAnomaly = anomalies.find(anomaly => 
      timestampsAreClose(point.timestamp, anomaly.timestamp, 5 * INTERVALS.POLLING) // 5 second tolerance
    );
    
    return {
      ...point,
      hasAnomaly: !!matchingAnomaly,
      anomaly: matchingAnomaly,
    };
  });
};

/**
 * Create red zones from anomaly clusters
 * Groups nearby anomalies into continuous visual zones
 */
export const createAnomalyZones = (
  anomalies: Anomaly[],
  telemetryData: TelemetryPoint[]
): RedZone[] => {
  if (anomalies.length === 0) return [];
  
  // Get all anomaly timestamps
  const timestamps = anomalies.map(a => a.timestamp);
  
  // Group into continuous ranges
  const ranges = groupTimestampsIntoRanges(timestamps, 300000); // 5 minute max gap
  
  // Convert ranges to RedZones with associated anomalies
  return ranges.map(range => {
    const zoneAnomalies = anomalies.filter(anomaly => {
      const anomalyTime = new Date(anomaly.timestamp).getTime();
      const startTime = new Date(range.start).getTime();
      const endTime = new Date(range.end).getTime();
      return anomalyTime >= startTime && anomalyTime <= endTime;
    });
    
    return {
      start: range.start,
      end: range.end,
      anomalies: zoneAnomalies,
    };
  });
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
    if (anomaly.telemetry_type !== telemetryType) {
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
 * Get anomaly statistics for a dataset
 */
export const getAnomalyStats = (anomalies: Anomaly[]) => {
  const stats = {
    total: anomalies.length,
    byType: {} as Record<string, number>,
    byTelemetryType: {} as Record<string, number>,
    severityDistribution: {} as Record<string, number>,
    timeRange: {
      earliest: '',
      latest: '',
    },
  };
  
  if (anomalies.length === 0) return stats;
  
  // Count by anomaly type
  anomalies.forEach(anomaly => {
    stats.byType[anomaly.anomaly_type] = (stats.byType[anomaly.anomaly_type] || 0) + 1;
    stats.byTelemetryType[anomaly.telemetry_type] = (stats.byTelemetryType[anomaly.telemetry_type] || 0) + 1;
  });
  
  // Find time range
  const timestamps = anomalies.map(a => new Date(a.timestamp).getTime()).sort();
  stats.timeRange.earliest = new Date(timestamps[0]).toISOString();
  stats.timeRange.latest = new Date(timestamps[timestamps.length - 1]).toISOString();
  
  return stats;
};

/**
 * Create tooltip content for anomaly visualization
 */
export const createAnomalyTooltip = (anomaly: Anomaly): string => {
  const formattedTime = new Date(anomaly.timestamp).toLocaleString();
  return `Anomaly: ${anomaly.anomaly_type}
Value: ${anomaly.anomaly_value}
Time: ${formattedTime}
Type: ${anomaly.telemetry_type}`;
};

/**
 * Determine the visual style for an anomaly based on its type
 */
export const getAnomalyStyle = (anomalyType: string) => {
  const styles: Record<string, { color: string; radius: number; opacity: number }> = {
    'threshold_exceeded': { color: '#ef4444', radius: 3, opacity: 0.8 },
    'spike': { color: '#f97316', radius: 4, opacity: 0.9 },
    'drop': { color: '#3b82f6', radius: 4, opacity: 0.9 },
    'pattern_break': { color: '#8b5cf6', radius: 3, opacity: 0.7 },
    'default': { color: '#dc2626', radius: 3, opacity: 0.8 },
  };
  
  return styles[anomalyType] || styles.default;
};