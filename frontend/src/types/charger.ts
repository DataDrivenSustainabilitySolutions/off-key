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
  valueType?: "number" | "boolean";
  data: TelemetryDataPoint[];
  cursor?: TelemetryCursor;
}

/** An alarm, named by catalogue device and readings. */
export interface Alarm {
  alarm_id: string;
  timestamp: string;
  /** Null for readings without a device, or when the catalogue no longer has them. */
  device_id: string | null;
  /** The device's name, or the broker's for readings without a device. */
  device_label: string | null;
  /** Catalogue readings the alarm is about; removed readings are left out. */
  reading_ids: string[];
  reading_labels: Record<string, string>;
  /** Raised over several readings together; empty reading_ids then mean "not recorded". */
  multivariate: boolean;
  alarm_type: string;
  value: number;
  // 'tail_pvalue': value is a tail probability (0-1, lower = more severe).
  // 'zscore': value is a z-score (legacy rows, higher = more severe).
  // null: predates this field.
  value_type: 'tail_pvalue' | 'conformal_pvalue' | 'zscore' | null;
  /** Historical and manually created alarms have no originating monitor. */
  monitor_id: string | null;
}

interface AlarmCursor {
  timestamp: string;
  alarm_id: string;
}

export interface AlarmQuery {
  reading_ids?: string[];
  reading_id?: string;
  monitor_id?: string;
  since?: string;
  until?: string;
  max_p_value?: number;
  limit?: number;
  before?: AlarmCursor;
}

export interface AlarmPage {
  items: Alarm[];
  next: AlarmCursor | null;
  /** Every match, not only this page. */
  summary: { count: number; devices: number; latest: string | null };
  /** Readings with alarms in the scope, before the narrowing filters. */
  readings: { reading_id: string; device_id: string | null; device_label: string | null; label: string; count: number }[];
  unknown_reading_ids: string[];
}
