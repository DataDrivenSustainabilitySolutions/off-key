export type CollectionPolicy = {
  mode: "off" | "original" | "sample";
  interval_seconds: number;
};
export type CatalogSensor = {
  key: string;
  label: string;
  category: string;
  value_type: "number" | "boolean" | "text" | "identifier";
  unit: string | null;
  upstream_topic: string;
  policy: CollectionPolicy | null;
};
export type CatalogCharger = {
  id: string;
  local_id: string;
  label: string;
  policy: CollectionPolicy | null;
  sensors: CatalogSensor[];
};
export type CatalogSource = {
  id: string;
  label: string;
  host: string;
  port: number;
  verified: boolean;
  forward_port: number | null;
  chargers: CatalogCharger[];
};
export type Catalog = {
  schema_version: 1;
  provider: "ambibox";
  default_policy: CollectionPolicy;
  sources: CatalogSource[];
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
  sources?: Record<string, { status: string; error?: string }>;
};
export type CatalogSnapshot = {
  revision: number;
  catalog: Catalog;
  can_edit: boolean;
  collection: RuntimeState;
  ingress: RuntimeState;
  updated_at: string | null;
  updated_by: string | null;
};
export type CatalogPreview = {
  revision: number;
  catalog: Catalog;
  chargers: number;
  selected_sensors: number;
  sampled_rows_per_day_ceiling: number;
  original_rate_sensors: number;
  affected_monitors: { id: string; name: string }[];
};
export const pausedPolicy: CollectionPolicy = {
  mode: "off",
  interval_seconds: 10,
};
export const effectivePolicy = (
  catalog: Catalog,
  charger: CatalogCharger,
  sensor: CatalogSensor,
) => sensor.policy ?? charger.policy ?? catalog.default_policy;

export function runtimeLabel(state: RuntimeState, revision: number): string {
  if (revision === 0) return "Not configured";
  if (state.status === "disabled") return "Disabled by operator";
  if (!state.checked_at || Date.now() - Date.parse(state.checked_at) > 15000)
    return "Waiting for worker";
  if (state.revision !== revision) return "Applying saved changes";
  return state.status?.replace(/_/g, " ") ?? "Waiting";
}

export type StorageStatus = {
  database_size_bytes: number;
  retention_policies: {
    table: "telemetry" | "monitoring_evidence";
    retention_days: number | null;
    scheduled: boolean;
  }[];
  checked_at: string;
};
