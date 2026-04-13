import { useEffect, useMemo } from "react";
import { TELEMETRY_THRESHOLDS } from "./constants";
import { clientLogger } from "@/lib/logger";

type DataPoint = {
  timestamp: string;
  value: number;
};

type RedZone = {
  start: string;
  end: string;
};

/**
 * @deprecated Use anomaly-based visualization instead.
 */
export function useRedZones(
  data: DataPoint[],
  threshold = TELEMETRY_THRESHOLDS.CPU_TEMPERATURE
): RedZone[] {
  useEffect(() => {
    clientLogger.warn({
      event: "telemetry.red_zones_deprecated",
      message:
        "useRedZones is deprecated. Use anomaly-based visualization with createAnomalyZones() instead.",
    });
  }, []);

  return useMemo(() => {
    const zones: RedZone[] = [];
    let start: string | null = null;

    for (let index = 0; index < data.length; index += 1) {
      const point = data[index];
      if (point.value >= threshold) {
        if (start === null) {
          start = point.timestamp;
        }
        continue;
      }

      if (start !== null) {
        zones.push({ start, end: point.timestamp });
        start = null;
      }
    }

    if (start !== null) {
      zones.push({ start, end: data[data.length - 1].timestamp });
    }

    return zones;
  }, [data, threshold]);
}
