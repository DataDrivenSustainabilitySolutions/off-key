/**
 * Shared charger and telemetry types
 *
 * Consolidates interfaces that were previously duplicated across:
 * - FetchContext.tsx
 * - ChargerContext.tsx
 * - TelemetryContext.tsx
 */

// Base charger data from API
export interface Charger {
  charger_id: string;
  charger_name: string | null;
  last_seen: string;
  online: boolean;
  state: string;
  created: string;
}

// Telemetry data point (CPU usage, thermal, etc.)
export interface TelemetryDataPoint {
  timestamp: string;
  value: number;
}

// Telemetry data with charger association
export interface TelemetryData {
  charger_id: string;
  timestamp: string;
  value: number;
}

// Combined charger data with optional telemetry values
export interface CombinedChargerData {
  charger_id: string;
  charger_name: string | null;
  online: boolean;
  state: string;
  last_seen: string;
  value1?: number | null; // CPU usage
  value2?: number | null; // CPU thermal
}

// Monitoring data point (system metrics)
export interface MonitoringData {
  type: string;
  value: number;
}

// Telemetry type categorization
export type TelemetryCategory = 'cpu' | 'system' | 'controller' | 'other';

// Categorized telemetry data
export interface TelemetryTypeData {
  type: string;
  category: TelemetryCategory;
  data: TelemetryDataPoint[];
}

// Anomaly detection result
export interface Anomaly {
  charger_id: string;
  timestamp: string;
  telemetry_type: string;
  anomaly_type: string;
  anomaly_value: number;
}

// Status filter options
export type StatusFilter = 'all' | 'online' | 'offline';

/**
 * Helper function to categorize telemetry type
 */
export function getTelemetryCategory(telemetryType: string): TelemetryCategory {
  const type = telemetryType.toLowerCase();
  if (type.includes('cpu') || type.includes('thermal')) {
    return 'cpu';
  }
  if (type.startsWith('system')) {
    return 'system';
  }
  if (type.startsWith('controller')) {
    return 'controller';
  }
  return 'other';
}
