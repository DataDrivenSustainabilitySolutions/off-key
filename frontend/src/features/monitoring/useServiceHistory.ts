import { useCallback, useMemo, useState, useSyncExternalStore } from "react";
import { usePollingLoop } from "@/hooks/use-polling";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { drainForward, EVIDENCE_PAGE_SIZE, TELEMETRY_PAGE_SIZE } from "@/lib/forward-pages";
import { getTelemetryCursor, getTelemetryData } from "@/lib/charger-api";
import { getMonitoringEvidenceCursor, mergeMonitoringChartEvidence } from "@/lib/monitoring-chart";
import { INTERVALS } from "@/lib/constants";
import type { MonitoringChartEvidence, MonitoringEvidenceCursor } from "@/types/monitoring";
import type { TelemetryCursor } from "@/types/charger";
import type { SystemConnection } from "@/types/system";
import { ReadingHistoryCache, readingHistoryKey } from "@/domain/readings/readingHistoryCache";
import { mergeReadingHistory } from "@/domain/readings/readingMonitoring";
import type { MonitoringInput } from "@/domain/monitoring/serviceModel";

type Input = { id: string; key: string; entityId: string; telemetryType: string };

class HistoryCursors {
  readonly telemetry = new Map<string, TelemetryCursor | undefined>();
  readonly evidence = new Map<string, MonitoringEvidenceCursor | undefined>();
  private seeded = false;
  constructor(private readonly cache: ReadingHistoryCache, private readonly inputs: Input[]) {}

  /** Resume from cached telemetry fetched within the last 30 seconds. */
  seed() {
    if (this.seeded) return;
    this.seeded = true;
    for (const input of this.inputs) {
      const previous = this.cache.get(input.key);
      if (previous?.telemetryFetchedAt && Date.now() - previous.telemetryFetchedAt < 30_000) this.telemetry.set(input.key, previous.telemetryCursor);
    }
  }
}

/** Telemetry polls per visible reading; joint evidence polls once per entity. */
export function useServiceHistory(
  serviceId: string,
  inputs: MonitoringInput[],
  allInputs: MonitoringInput[],
  connections: SystemConnection[],
  sharedCache?: ReadingHistoryCache,
) {
  const [localCache] = useState(() => new ReadingHistoryCache());
  const cache = sharedCache ?? localCache;
  // Stable scalar request identities avoid restarting polls on service heartbeats.
  const requests = JSON.stringify(inputs.flatMap(({ stream, binding }) => {
    const key = readingHistoryKey(connections.find(item => item.id === stream.connection_id), stream, binding.entity_id, binding.telemetry_key);
    return key ? [{ id: stream.id, key, entityId: binding.entity_id, telemetryType: binding.telemetry_key }] : [];
  }));
  const entities = JSON.stringify([...new Set(allInputs.map(input => input.binding.entity_id))].sort());
  const context = useMemo(() => ({ inputs: JSON.parse(requests) as Input[], entities: JSON.parse(entities) as string[],
    serviceKey: `monitoring-history:${serviceId}` }), [requests, entities, serviceId]);
  const keys = useMemo(() => [context.serviceKey, ...context.inputs.map(input => input.key)], [context]);
  const subscribe = useCallback((notify: () => void) => {
    const unsubscribes = keys.map(key => cache.subscribe(key, notify));
    return () => unsubscribes.forEach(unsubscribe => unsubscribe());
  }, [cache, keys]);
  const getRevision = useCallback(() => cache.revision, [cache]);
  const revision = useSyncExternalStore(subscribe, getRevision);
  const snapshot = useMemo(() => ({
    revision,
    histories: new Map(context.inputs.map(input => [input.id, cache.snapshot(input.key)])),
    monitoring: cache.snapshot(context.serviceKey),
  }), [cache, context, revision]);

  // Cursors live as long as the request context; both loops share them.
  const cursors = useMemo(() => new HistoryCursors(cache, context.inputs), [cache, context]);
  const pollTelemetry = useCallback(async (signal: AbortSignal) => {
    cursors.seed();
    await Promise.allSettled(context.inputs.map(async input => {
      try {
        const initial = cursors.telemetry.get(input.key);
        const points = await drainForward({
          cursor: initial,
          fetchPage: cursor => getTelemetryData(input.entityId, input.telemetryType, signal, cursor),
          cursorOf: getTelemetryCursor,
          pageSize: TELEMETRY_PAGE_SIZE,
        });
        if (signal.aborted) return;
        const next = getTelemetryCursor(points) ?? initial;
        cursors.telemetry.set(input.key, next);
        cache.update(input.key, entry => ({ ...entry, telemetryCursor: next, telemetryFetchedAt: Date.now(), data: { ...entry.data,
          binding: { entityId: input.entityId, telemetryType: input.telemetryType },
          telemetry: mergeReadingHistory(entry.data.telemetry, points, 2000), loading: false, error: "",
        } }));
      } catch {
        if (!signal.aborted) cache.update(input.key, entry => ({ ...entry, data: { ...entry.data, loading: false, error: "Reading history could not be updated." } }));
      }
    }));
  }, [cache, context, cursors]);
  const pollEvidence = useCallback(async (signal: AbortSignal) => {
    const results = await Promise.allSettled(context.entities.map(async entityId => {
      const initial = cursors.evidence.get(entityId);
      const rows = await drainForward({
        cursor: initial,
        fetchPage: cursor => apiUtils.get<MonitoringChartEvidence[]>(API_CONFIG.ENDPOINTS.MONITORING.CHART_EVIDENCE(entityId, cursor, serviceId),
          { signal, redirectOnUnauthorized: false }),
        cursorOf: getMonitoringEvidenceCursor,
        pageSize: EVIDENCE_PAGE_SIZE,
      });
      if (!signal.aborted) cursors.evidence.set(entityId, getMonitoringEvidenceCursor(rows) ?? initial);
      return rows.filter(row => row.service_id === serviceId);
    }));
    if (signal.aborted) return;
    const rows = results.flatMap(result => result.status === "fulfilled" ? result.value : []);
    cache.update(context.serviceKey, entry => ({ ...entry, evidenceFetchedAt: Date.now(), data: { ...entry.data,
      evidence: mergeMonitoringChartEvidence(entry.data.evidence, rows), loading: false,
      error: results.some(result => result.status === "rejected") ? "Detector history could not be updated." : "",
    } }));
  }, [cache, context, cursors, serviceId]);
  const chain = { schedule: "after-completion", overlap: "skip", pauseWhenHidden: true, resumeOnVisible: true, startImmediately: true } as const;
  usePollingLoop(pollTelemetry, { ...chain, intervalMs: 2000 });
  usePollingLoop(pollEvidence, { ...chain, intervalMs: INTERVALS.DETAILS_UPDATE });
  return snapshot;
}
