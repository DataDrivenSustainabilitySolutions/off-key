import type { TelemetryDataPoint } from "./charger";

export interface HistoryPoint extends TelemetryDataPoint {
  minimum?: number;
  maximum?: number;
  count?: number;
  start?: string;
  end?: string;
  /** Client-side only: the column width of the raw view this reading came from. */
  column_ms?: number;
}

export interface TelemetryHistory {
  representation: "raw" | "mean";
  points: HistoryPoint[];
  interval_ms: number;
  sample_count: number;
  extent: [string, string] | null;
  /**
   * Raw views only. Above zero, each column of this width (counted from the epoch)
   * holds just its first, last, lowest and highest reading. Zero: every reading.
   */
  column_ms?: number;
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
