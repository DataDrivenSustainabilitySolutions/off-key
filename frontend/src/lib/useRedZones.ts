import { useMemo } from "react";
import { TELEMETRY_THRESHOLDS } from './constants';

/**
 * @deprecated This hook is deprecated in favor of anomaly-based visualization.
 * Use createAnomalyZones() from @/lib/anomaly-utils instead.
 * 
 * This hook creates red zones based on hardcoded thresholds, which should be
 * replaced with actual anomaly data from the database.
 * 
 * Migration guide:
 * 1. Fetch anomalies using loadAnomalies() from FetchContext
 * 2. Filter anomalies by telemetry type using filterAnomalies()
 * 3. Create zones using createAnomalyZones(anomalies, telemetryData)
 */

type DataPoint = {
  timestamp: string;
  value: number;
};

/**
 * @deprecated Use anomaly-based visualization instead
 */
export function useRedZones(data: DataPoint[], threshold = TELEMETRY_THRESHOLDS.CPU_TEMPERATURE) {
  console.warn(
    'useRedZones is deprecated. Use anomaly-based visualization with createAnomalyZones() instead.'
  );
  
  return useMemo(() => {
    const zones: { start: string; end: string }[] = [];
    let start: string | null = null;

    for (let i = 0; i < data.length; i++) {
      if (data[i].value >= threshold) {
        if (start === null) start = data[i].timestamp;
      } else {
        if (start !== null) {
          zones.push({ start, end: data[i].timestamp });
          start = null;
        }
      }
    }

    if (start !== null) {
      zones.push({ start, end: data[data.length - 1].timestamp });
    }

    return zones;
  }, [data, threshold]);
}
