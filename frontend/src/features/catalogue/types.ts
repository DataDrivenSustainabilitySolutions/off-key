export type Sample = { timestamp: number; value: number };
export type NodeTelemetry = {
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
