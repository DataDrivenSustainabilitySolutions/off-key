import { useCallback, useSyncExternalStore } from "react";
import type { Anomaly, TelemetryCursor, TelemetryDataPoint } from "@/types/charger";
import type { ActiveService, MonitoringChartEvidence, MonitoringEvidenceCursor } from "@/types/monitoring";
import type { ReadingMonitoringBinding } from "./readingMonitoring";
import type { SystemConnection, SystemStream } from "../spatial/systemTypes";

export type ReadingMonitoring = {
  binding?: ReadingMonitoringBinding;
  telemetry: TelemetryDataPoint[];
  evidence: MonitoringChartEvidence[];
  anomalies: Anomaly[];
  services: ActiveService[];
  loading?: boolean;
  error: string;
};
export type ReadingHistoryEntry = {
  data: ReadingMonitoring;
  telemetryCursor?: TelemetryCursor;
  evidenceCursor?: MonitoringEvidenceCursor;
  telemetryFetchedAt?: number;
  evidenceFetchedAt?: number;
};
export const EMPTY_READING_HISTORY: ReadingMonitoring = {
  telemetry: [], evidence: [], anomalies: [], services: [], loading: true, error: "",
};
export const READING_HISTORY_CACHE_LIMIT = 12;
export const READING_HISTORY_POINT_LIMIT = 32_768;

export function readingHistoryKey(
  connection: Pick<SystemConnection, "host" | "port" | "transport" | "tls"> | undefined,
  stream: Pick<SystemStream, "id" | "topic" | "payload_pointer" | "value_type"> | undefined,
  entityId?: string,
  telemetryType?: string,
): string | undefined {
  if (!connection?.host || !connection.port || !connection.transport || connection.tls === undefined || !stream) return;
  return JSON.stringify([stream.id, stream.topic, stream.payload_pointer, stream.value_type,
    connection.host, connection.port, connection.transport, connection.tls, entityId, telemetryType]);
}

export function useReadingHistorySnapshot(cache: ReadingHistoryCache | undefined, key?: string): ReadingMonitoring {
  const subscribe = useCallback((listener: () => void) => cache && key ? cache.subscribe(key, listener) : () => {}, [cache, key]);
  const snapshot = useCallback(() => cache && key ? cache.snapshot(key) : EMPTY_READING_HISTORY, [cache, key]);
  return useSyncExternalStore(subscribe, snapshot);
}

/** Owned by one signed-in workspace. Retains visited inputs, without polling them. */
export class ReadingHistoryCache {
  private entries = new Map<string, ReadingHistoryEntry>();
  private listeners = new Map<string, Set<() => void>>();
  readonly owner: string | number | null;
  constructor(owner: string | number | null = null) { this.owner = owner; }

  get(key: string): ReadingHistoryEntry | undefined { return this.entries.get(key); }
  snapshot(key: string): ReadingMonitoring { return this.entries.get(key)?.data ?? EMPTY_READING_HISTORY; }
  subscribe(key: string, listener: () => void): () => void {
    let listeners = this.listeners.get(key);
    if (!listeners) { listeners = new Set(); this.listeners.set(key, listeners); }
    listeners.add(listener);
    return () => { listeners.delete(listener); if (!listeners.size) this.listeners.delete(key); };
  }
  touch(key: string) {
    const entry = this.entries.get(key);
    if (entry) { this.entries.delete(key); this.entries.set(key, entry); }
  }
  update(key: string, update: (entry: ReadingHistoryEntry) => ReadingHistoryEntry) {
    const next = update(this.entries.get(key) ?? { data: EMPTY_READING_HISTORY });
    this.entries.delete(key); this.entries.set(key, next);
    let points = [...this.entries.values()].reduce((count, entry) => count + entry.data.telemetry.length + entry.data.evidence.length, 0);
    while (this.entries.size > READING_HISTORY_CACHE_LIMIT || points > READING_HISTORY_POINT_LIMIT) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined) break;
      const entry = this.entries.get(oldest)!;
      points -= entry.data.telemetry.length + entry.data.evidence.length;
      this.entries.delete(oldest);
      if (oldest !== key) this.notify(oldest);
    }
    this.notify(key);
  }
  private notify(key: string) { this.listeners.get(key)?.forEach(listener => listener()); }
}
