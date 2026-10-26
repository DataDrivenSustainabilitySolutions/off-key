export type CollectionPolicy = {
  mode: "off" | "original" | "sample";
  interval_seconds: number;
};
export type CollectionDiagnostics = {
  mqtt_connected: boolean;
  window_seconds: number;
  rates: Record<"received" | "accepted" | "invalid" | "overload_dropped" | "written", number | null>;
  last_received_at: string | null;
  last_database_write_at: string | null;
  original_queue: number;
  original_capacity: number;
  sample_slots: number;
  database_queue: number;
  database_capacity: number;
  database_retrying: boolean;
};
export type RuntimeState = {
  selected_sensors?: number;
  diagnostics?: CollectionDiagnostics;
  revision?: number;
  status?: string;
  checked_at?: string;
  error?: string;
  records_written?: number;
  counters?: Record<string, number>;
  sources?: Record<string, { state: string; error?: string }>;
};
export type CollectionStatus = { revision: number; collection: RuntimeState; ingress: RuntimeState };
export type StorageStatus = {
  database_size_bytes: number;
  retention_policies: {
    table: "telemetry" | "monitoring_evidence" | "anomalies";
    retention_days: number | null;
    scheduled: boolean;
  }[];
  storage_cap_bytes: number | null;
  storage_cap_scheduled: boolean;
  capped_size_bytes: number;
  checked_at: string;
};
