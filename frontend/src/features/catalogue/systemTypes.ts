import type { CollectionPolicy } from "../../types/collection";

export type SystemConnection = {
  id: string;
  label: string;
  protocol: "mqtt";
  host: string;
  port: number;
  transport: "tcp" | "websocket";
  tls: boolean;
  websocket_path?: string;
  credential_ref?: string;
};

export type SystemDevice = {
  id: string;
  label: string;
  connection_id?: string;
  parent_id?: string;
  kind: string;
};

export type SystemStream = {
  id: string;
  label: string;
  connection_id: string;
  device_id?: string;
  topic: string;
  payload_pointer?: string;
  value_type: "number" | "boolean" | "text" | "identifier";
  unit?: string;
  category: string;
  policy?: CollectionPolicy;
};

export type SystemGroup = {
  id: string;
  label: string;
  color?: string;
  member_ids: string[];
};

/** Declarative configuration only. Passwords and runtime readings are excluded. */
export type SystemDocument = {
  format: "aberration-system";
  schema_version: 1;
  label: string;
  default_policy: CollectionPolicy;
  connections: SystemConnection[];
  devices: SystemDevice[];
  streams: SystemStream[];
  groups: SystemGroup[];
};

export type SystemEntityKind = "connection" | "device" | "stream" | "group";
export type SystemRuntime = {
  mode: "configured_only" | "collection";
  message: string;
  collection_revision?: number;
  collection?: { revision?: number; status?: string; records_written?: number; counters?: Record<string, number> };
  ingress?: {
    revision?: number;
    status?: string;
    sources?: Record<string, { state: string; message?: string | null }>;
    readings?: Record<string, { fresh_received_at: string }>;
  };
  bindings?: Record<string, SystemReadingBinding>;
  collection_rules?: CollectionRule[];
  latest_readings?: Record<string, { value: number | boolean | string; received_at: string; is_snapshot: boolean }>;
};
export type SystemReadingBinding = {
  entity_id: string;
  connection_id?: string;
  telemetry_key: string;
  accepted_topic: string;
  policy: CollectionPolicy;
  policy_origin?: PolicyOrigin;
};
export type SystemCollectionPreview = {
  revision: number;
  collection_revision: number;
  selected_readings: number;
  sampled_rows_per_day_ceiling: number;
  original_rate_readings: number;
  affected_monitors: Array<{ id: string; name: string }>;
  changed_readings?: number;
  starting_readings?: number;
  stopping_readings?: number;
  rate_changed_readings?: number;
  bindings?: Record<string, Pick<SystemReadingBinding, "policy" | "policy_origin">>;
  rules?: CollectionRule[];
};
export type SystemSnapshot = {
  revision: number;
  document: SystemDocument;
  can_edit: boolean;
  storage_origin: "saved" | "empty";
  runtime: SystemRuntime;
  updated_at?: string | null;
  updated_by?: string | null;
};

export type RuleScope = { kind: "broker" | "topic" | "reading"; connection_id: string; topic_prefix?: string | null; reading_id?: string | null };
export type CollectionRule = { scope: RuleScope; policy: CollectionPolicy | null; include_future_readings: boolean; admitted_before: number };
export type RuleEdit =
  | { scope: RuleScope; operation: "set"; policy: CollectionPolicy; include_future_readings?: boolean }
  | { scope: RuleScope; operation: "inherit" }
  | { scope: RuleScope; operation: "restore"; restore_rule: CollectionRule | null };
export type RuleChange = { expected_revision: number; expected_collection_revision: number; rule_changes: RuleEdit[]; pause_affected_monitors?: boolean };
export type PolicyOrigin = { scope: RuleScope | null; inherited: boolean; needs_review: boolean };
