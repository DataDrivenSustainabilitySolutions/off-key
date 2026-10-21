import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { getTelemetryCursor, getTelemetryData } from "@/lib/charger-api";
import { getMonitoringEvidenceCursor, mergeMonitoringChartEvidence } from "@/lib/monitoring-chart";
import { INTERVALS } from "@/lib/constants";
import type { MonitoringChartEvidence, MonitoringEvidenceCursor } from "@/types/monitoring";
import type { TelemetryCursor, TelemetryDataPoint } from "@/types/charger";
import type { SystemConnection } from "../catalogue/systemTypes";
import { ReadingHistoryCache, readingHistoryKey } from "../explorer/readingHistoryCache";
import { mergeReadingHistory } from "../explorer/readingMonitoring";
import type { MonitoringInput } from "./serviceModel";

type Input = { id: string; key: string; entityId: string; telemetryType: string };

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

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    const telemetryCursors = new Map<string, TelemetryCursor | undefined>();
    const evidenceCursors = new Map<string, MonitoringEvidenceCursor | undefined>();
    for (const input of context.inputs) {
      const previous = cache.get(input.key);
      if (previous?.telemetryFetchedAt && Date.now() - previous.telemetryFetchedAt < 30_000) telemetryCursors.set(input.key, previous.telemetryCursor);
    }
    let telemetryTimer: ReturnType<typeof setTimeout> | undefined;
    let evidenceTimer: ReturnType<typeof setTimeout> | undefined;
    let telemetryPending = false;
    let evidencePending = false;
    const pollTelemetry = async () => {
      if (signal.aborted || document.hidden || telemetryPending) return;
      clearTimeout(telemetryTimer);
      telemetryPending = true;
      await Promise.allSettled(context.inputs.map(async input => {
        try {
          const points: Array<TelemetryDataPoint & { created?: string }> = [];
          const initial = telemetryCursors.get(input.key);
          let cursor = initial;
          for (let page = 0; page < 10; page++) {
            const incoming = await getTelemetryData(input.entityId, input.telemetryType, signal, cursor);
            points.push(...incoming);
            const next = getTelemetryCursor(incoming);
            if (!initial || incoming.length < 1000 || !next || JSON.stringify(next) === JSON.stringify(cursor)) break;
            cursor = next;
          }
          if (signal.aborted) return;
          const next = getTelemetryCursor(points) ?? initial;
          telemetryCursors.set(input.key, next);
          cache.update(input.key, entry => ({ ...entry, telemetryCursor: next, telemetryFetchedAt: Date.now(), data: { ...entry.data,
            binding: { entityId: input.entityId, telemetryType: input.telemetryType },
            telemetry: mergeReadingHistory(entry.data.telemetry, points, 2000), loading: false, error: "",
          } }));
        } catch {
          if (!signal.aborted) cache.update(input.key, entry => ({ ...entry, data: { ...entry.data, loading: false, error: "Reading history could not be updated." } }));
        }
      }));
      telemetryPending = false;
      if (!signal.aborted) telemetryTimer = setTimeout(() => void pollTelemetry(), 2000);
    };
    const pollEvidence = async () => {
      if (signal.aborted || document.hidden || evidencePending) return;
      clearTimeout(evidenceTimer);
      evidencePending = true;
      const results = await Promise.allSettled(context.entities.map(async entityId => {
        const rows: MonitoringChartEvidence[] = [];
        const initial = evidenceCursors.get(entityId);
        let cursor = initial;
        for (let page = 0; page < 10; page++) {
          const incoming = await apiUtils.get<MonitoringChartEvidence[]>(API_CONFIG.ENDPOINTS.MONITORING.CHART_EVIDENCE(entityId, cursor, serviceId),
            { signal, redirectOnUnauthorized: false });
          rows.push(...incoming);
          const next = getMonitoringEvidenceCursor(incoming);
          if (!initial || incoming.length < 2000 || !next || JSON.stringify(next) === JSON.stringify(cursor)) break;
          cursor = next;
        }
        if (!signal.aborted) evidenceCursors.set(entityId, getMonitoringEvidenceCursor(rows) ?? initial);
        return rows.filter(row => row.service_id === serviceId);
      }));
      evidencePending = false;
      if (signal.aborted) return;
      const rows = results.flatMap(result => result.status === "fulfilled" ? result.value : []);
      cache.update(context.serviceKey, entry => ({ ...entry, evidenceFetchedAt: Date.now(), data: { ...entry.data,
        evidence: mergeMonitoringChartEvidence(entry.data.evidence, rows), loading: false,
        error: results.some(result => result.status === "rejected") ? "Detector history could not be updated." : "",
      } }));
      evidenceTimer = setTimeout(() => void pollEvidence(), INTERVALS.DETAILS_UPDATE);
    };
    const resume = () => { if (!document.hidden) { void pollTelemetry(); void pollEvidence(); } };
    document.addEventListener("visibilitychange", resume);
    resume();
    return () => { controller.abort(); clearTimeout(telemetryTimer); clearTimeout(evidenceTimer); document.removeEventListener("visibilitychange", resume); };
  }, [cache, context, serviceId]);
  return snapshot;
}
