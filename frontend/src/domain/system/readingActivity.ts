import type { SystemLiveTelemetry } from "./systemLiveTelemetry";
import type { LiveStatus } from "@/types/system-live";
import type { SystemRuntime } from "@/types/system";
import type { ExplorerNode } from "./navigationIndex";

// A reading is receiving while its current gap stays within a few of its long
// usual gaps, so a source that reports every few minutes does not flicker to waiting.
// The floor absorbs status polling, browser clock skew and short broker hiccups
// for fast and newly seen sources; the cap bounds a silent source.
const MIN_ACTIVITY_WINDOW_MS = 2 * 60_000;
const MAX_ACTIVITY_WINDOW_MS = 30 * 60_000;
const USUAL_GAPS = 3;
// A broker that is reconnecting keeps its readings until the window runs out.
const LISTENING_STATES = new Set(["connected", "connecting", "reconnecting"]);
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
  // A receipt that looks newer than now only means the browser clock is behind.
  return now - time < window;
}

function receivingLabel(window: number, simulated = false, reconnecting = false) {
  const span = window < 60_000 ? `${Math.round(window / 1000)} seconds`
    : `${Math.round(window / 60_000)} ${Math.round(window / 60_000) === 1 ? "minute" : "minutes"}`;
  return `${reconnecting ? "Broker reconnecting, received" : "Receiving"} ${simulated ? "simulated " : ""}data (last ${span})`;
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
    const sourceState = runtime?.ingress?.sources?.[connectionId ?? ""]?.state;
    const recording = persistentReady && binding && binding.policy.mode !== "off"
      && LISTENING_STATES.has(sourceState ?? "");
    const receipt = runtime?.ingress?.readings?.[id];
    const window = activityWindow(receipt?.typical_interval_seconds);
    if (recording && recent(receipt?.fresh_received_at, now, window)) {
      return { receiving: true, label: receivingLabel(window, false, sourceState !== "connected") };
    }
    const connection = status?.connections.find(item => item.connection_id === connectionId && LISTENING_STATES.has(item.state));
    const preview = source?.liveStreamIds.includes(id) && status?.active
      && (status.phase === "live" || status.phase === "reconnecting") && connection;
    if (preview) {
      const snapshot = source?.telemetry.getSnapshot(id);
      const window = activityWindow(snapshot?.typicalInterval);
      if (snapshot && snapshot.received > 0 && recent(snapshot.lastSeen, now, window)) {
        return { receiving: true, label: receivingLabel(window, status?.dataSource === "simulated", connection.state !== "connected") };
      }
    }
    listening ||= !!(recording && sourceState === "connected" || preview && status?.phase === "live" && connection.state === "connected");
  }
  return { receiving: false, label: listening ? "Listening, waiting for fresh data" : "Not listening" };
}
