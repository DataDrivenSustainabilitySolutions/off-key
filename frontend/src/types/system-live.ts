export type Sample = { timestamp: number; value: number };
type NodeTelemetry = {
  value: number;
  lastSeen: number;
  received: number;
  rate: number;
  samples: readonly Sample[];
};
export type TelemetryMessage = Sample & { nodeId: string };
export interface LiveTelemetryStore {
  getSnapshot(id: string): NodeTelemetry | undefined;
  subscribe(listener: (message: TelemetryMessage) => void): () => void;
}

export type LiveValue = number | boolean | string | null;
export type LiveConnection = {
  connection_id: string;
  state:
    | "blocked"
    | "connecting"
    | "connected"
    | "reconnecting"
    | "error"
    | "stopped";
  message: string | null;
  received_messages: number;
  fresh_count: number;
  retained_count: number;
  fresh_received_at: string | null;
  rate_hz: number;
};
export type LiveStream = {
  stream_id: string;
  value: LiveValue;
  received_at: string | null;
  is_retained: boolean;
  received_count: number;
  fresh_count: number;
  retained_count: number;
  decode_errors: number;
  fresh_received_at: string | null;
  rate_hz: number;
  sequence: number;
};
export type LiveSample = {
  sequence: number;
  stream_id: string;
  received_at: string;
  value: Exclude<LiveValue, null>;
  is_retained: boolean;
};
export type LiveBatch = {
  mode: "live" | "configured_only";
  data_source?: "broker" | "simulated";
  revision: number;
  sequence: number;
  reset: boolean;
  connections: LiveConnection[];
  streams: LiveStream[];
  samples: LiveSample[];
  limits: {
    max_samples: number;
    history_seconds: number;
    sample_interval_seconds: number;
    lease_seconds: number;
    connect_timeout_seconds?: number;
  };
};
export type LiveLease = {
  lease_id: string;
  expires_in_seconds: number;
  telemetry: LiveBatch;
};
export type LiveStatus = {
  dataSource?: "broker" | "simulated";
  phase:
    | "idle"
    | "connecting"
    | "live"
    | "waiting"
    | "reconnecting"
    | "blocked"
    | "error"
    | "paused";
  message: string;
  observing: boolean;
  active: boolean;
  connections: readonly LiveConnection[];
};
export type LiveNodeSnapshot = NodeTelemetry & {
  latestValue: LiveValue;
  receivedAt: number | null;
  retained: boolean;
  retainedCount: number;
  decodeErrors: number;
  isAggregate: boolean;
};
