import type { SystemLiveTelemetry } from "../catalogue/systemLiveTelemetry";
import type { LiveStatus } from "../catalogue/systemLiveTypes";
import type { SystemRuntime } from "../catalogue/systemTypes";
import type { ExplorerNode } from "./navigationIndex";

export const READING_ACTIVITY_WINDOW_MS = 30_000;
export type ReadingActivitySource = {
  telemetry: SystemLiveTelemetry;
  liveStreamIds: readonly string[];
  runtime?: SystemRuntime;
};

export const isReadingLeaf = (node: ExplorerNode) => !node.children.length && node.streamIds.length > 0
  && (node.kind === "reading" || node.kind === "topic");

function recent(value: string | number | null | undefined, now: number) {
  const time = typeof value === "string" ? Date.parse(value) : value;
  if (time == null || !Number.isFinite(time)) return false;
  const age = now - time;
  return age >= -5_000 && age < READING_ACTIVITY_WINDOW_MS;
}

/** Activity comes from current subscriptions and fresh receipts, independently of sampling. */
export function readingActivity(node: ExplorerNode, source: ReadingActivitySource | undefined, status: LiveStatus | undefined, now: number) {
  const runtime = source?.runtime;
  const persistentReady = runtime?.mode === "collection" && runtime.collection?.status === "applied"
    && runtime.ingress?.status === "applied" && runtime.ingress.revision === runtime.collection_revision;
  let listening = false;
  for (const id of node.streamIds) {
    const binding = runtime?.bindings?.[id];
    const connectionId = binding?.connection_id ?? node.connectionId;
    const recording = persistentReady && binding && binding.policy.mode !== "off"
      && runtime.ingress?.sources?.[connectionId ?? ""]?.state === "connected";
    if (recording && recent(runtime.ingress?.readings?.[id]?.fresh_received_at, now)) {
      return { receiving: true, label: "Receiving data (last 30 seconds)" };
    }
    const preview = source?.liveStreamIds.includes(id) && status?.active && status.phase === "live"
      && status.connections.some(connection => connection.connection_id === connectionId && connection.state === "connected");
    if (preview) {
      const snapshot = source?.telemetry.getSnapshot(id);
      if (snapshot && snapshot.received > 0 && recent(snapshot.lastSeen, now)) {
        return { receiving: true, label: status?.dataSource === "simulated"
          ? "Receiving simulated data (last 30 seconds)" : "Receiving data (last 30 seconds)" };
      }
    }
    listening ||= !!(recording || preview);
  }
  return { receiving: false, label: listening ? "Listening, waiting for fresh data" : "Not listening" };
}
