import type { TelemetryDataPoint } from "./charger";

export interface HistoryPoint extends TelemetryDataPoint {
  minimum?: number;
  maximum?: number;
  count?: number;
  start?: string;
  end?: string;
}

export interface TelemetryHistory {
  representation: "raw" | "mean";
  points: HistoryPoint[];
  interval_ms: number;
  sample_count: number;
  extent: [string, string] | null;
  truncated: boolean;
}

export interface HistoryPreference {
  mode: "auto" | "raw";
  windowMs?: number;
}

export interface HistoryRequest {
  startMs?: number;
  endMs?: number;
  buckets?: number;
  view?: "auto" | "raw";
  windowMs?: number;
}
