import { useMemo } from "react";

//React Hook for Red Zone initialisation at the Line Chart in the Detailspage

type DataPoint = {
  timestamp: string;
  value: number;
};
//Red Zones for the CPU Usage at the Moment with critical Usage at 80 or above
export function useRedZones(data: DataPoint[], threshold = 80) {
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
