import type { SystemLiveTelemetry } from "./systemLiveTelemetry";
import type { LiveStatus } from "@/types/system-live";
import type { SystemRuntime } from "@/types/system";
import type { ExplorerNode } from "./navigationIndex";

// A reading is receiving while its current gap stays within a few of its usual
// gaps, so a source that reports every few minutes does not flicker to waiting.
// Fast and newly seen sources keep the floor; the cap bounds a silent source.
const MIN_ACTIVITY_WINDOW_MS = 30_000;
const MAX_ACTIVITY_WINDOW_MS = 30 * 60_000;
const USUAL_GAPS = 3;
export type ReadingActivitySource = {
  telemetry: SystemLiveTelemetry;
  liveStreamIds: readonly string[];
  runtime?: SystemRuntime;
};

export const isReadingLeaf = (node: ExplorerNode) => !node.children.length && node.streamIds.length > 0
  && (node.kind === "reading" || node.kind === "topic");

export function activityWindow(typicalSeconds: number | null | undefined) {
  const usual = typicalSeconds != null && Number.isFinite(typicalSeconds) ? typicalSeconds * 1000 * USUAL_GAPS : 0;
  return Math.min(MAX_ACTIVITY_WINDOW_MS, Math.max(MIN_ACTIVITY_WINDOW_MS, usual));
}

function recent(value: string | number | null | undefined, now: number, window: number) {
  const time = typeof value === "string" ? Date.parse(value) : value;
  if (time == null || !Number.isFinite(time)) return false;
  const age = now - time;
  return age >= -5_000 && age < window;
}

function receivingLabel(window: number, simulated = false) {
  const span = window < 60_000 ? `${Math.round(window / 1000)} seconds`
    : `${Math.round(window / 60_000)} ${Math.round(window / 60_000) === 1 ? "minute" : "minutes"}`;
  return `Receiving ${simulated ? "simulated " : ""}data (last ${span})`;
}

/** Activity comes from current subscriptions and fresh receipts, independently of sampling. */
export function readingActivity(node: Pick<ExplorerNode, "streamIds" | "connectionId">, source: ReadingActivitySource | undefined, status: LiveStatus | undefined, now: number) {
  const runtime = source?.runtime;
  const persistentReady = runtime?.mode === "collection" && runtime.collection?.status === "applied"
    && runtime.ingress?.status === "applied" && runtime.ingress.revision === runtime.collection_revision;
  let listening = false;
  for (const id of node.streamIds) {
    const binding = runtime?.bindings?.[id];
    const connectionId = binding?.connection_id ?? node.connectionId;
    const recording = persistentReady && binding && binding.policy.mode !== "off"
      && runtime.ingress?.sources?.[connectionId ?? ""]?.state === "connected";
    const receipt = runtime?.ingress?.readings?.[id];
    const window = activityWindow(receipt?.typical_interval_seconds);
    if (recording && recent(receipt?.fresh_received_at, now, window)) {
      return { receiving: true, label: receivingLabel(window) };
    }
    const preview = source?.liveStreamIds.includes(id) && status?.active && status.phase === "live"
      && status.connections.some(connection => connection.connection_id === connectionId && connection.state === "connected");
    if (preview) {
      const snapshot = source?.telemetry.getSnapshot(id);
      const window = activityWindow(snapshot?.typicalInterval);
      if (snapshot && snapshot.received > 0 && recent(snapshot.lastSeen, now, window)) {
        return { receiving: true, label: receivingLabel(window, status?.dataSource === "simulated") };
      }
    }
    listening ||= !!(recording || preview);
  }
  return { receiving: false, label: listening ? "Listening, waiting for fresh data" : "Not listening" };
}
