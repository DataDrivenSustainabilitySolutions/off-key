/**
 * Shared measurement and alarm types
 */

// Telemetry data point (CPU usage, thermal, etc.)
export interface TelemetryDataPoint {
  timestamp: string;
  value: number;
}

export interface TelemetryCursor {
  created: string;
  timestamp: string;
}

// Categorized telemetry data
export interface TelemetryTypeData {
  /** The catalogue reading this series draws. */
  type: string;
  label?: string;
  category: string;
  unit?: string;
  data: TelemetryDataPoint[];
  cursor?: TelemetryCursor;
}

// Anomaly detection result
export interface Anomaly {
  anomaly_id: string;
  charger_id: string;
  // Historical and manually created records have no originating monitor.
  service_id?: string | null;
  timestamp: string;
  telemetry_type: string;
  anomaly_type: string;
  anomaly_value: number;
  // 'tail_pvalue': anomaly_value is a tail probability (0-1, lower = more severe).
  // 'zscore': anomaly_value is a z-score (legacy rows, higher = more severe).
  // null: predates this field.
  value_type: 'tail_pvalue' | 'conformal_pvalue' | 'zscore' | null;
  // Exact telemetry streams involved in this anomaly. null/undefined indicates
  // legacy data where the set was not persisted.
  sensor_set?: string[] | null;
}

/** An alarm as Reporting answers it: with the catalogue's names. */
export interface ReportedAnomaly extends Anomaly {
  entity_label: string;
  telemetry_label: string | null;
  readings: { key: string; label: string }[];
}

interface AnomalyCursor {
  timestamp: string;
  anomaly_id: string;
}

export interface AnomalyQuery {
  stream_ids?: string[];
  reading?: { charger_id: string; telemetry_key: string };
  service_id?: string;
  since?: string;
  until?: string;
  max_p_value?: number;
  limit?: number;
  before?: AnomalyCursor;
}

export interface AnomalyPage {
  items: ReportedAnomaly[];
  next: AnomalyCursor | null;
  /** Every match, not only this page. */
  summary: { count: number; entities: number; latest: string | null };
  /** Readings with alarms in the scope, before the narrowing filters. */
  readings: { charger_id: string; telemetry_key: string; entity_label: string; label: string; count: number }[];
  unknown_stream_ids: string[];
}
