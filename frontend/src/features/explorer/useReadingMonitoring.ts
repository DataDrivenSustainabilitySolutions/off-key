import { useEffect, useMemo, useState } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { getTelemetryCursor, getTelemetryData } from "@/lib/charger-api";
import { INTERVALS } from "@/lib/constants";
import { buildDeviceTelemetryTopic } from "@/lib/mqtt-topics";
import { mqttFiltersOverlap } from "@/lib/monitoring-services";
import { getMonitoringEvidenceCursor, mergeMonitoringChartEvidence } from "@/lib/monitoring-chart";
import type { Anomaly, TelemetryDataPoint } from "@/types/charger";
import type { ActiveService, MonitoringChartEvidence } from "@/types/monitoring";
import type { SystemConnection, SystemStream, SystemReadingBinding } from "../catalogue/systemTypes";
import { mergeReadingHistory, type ReadingMonitoringBinding } from "./readingMonitoring";
import { EMPTY_READING_HISTORY, ReadingHistoryCache, readingHistoryKey, useReadingHistorySnapshot } from "./readingHistoryCache";
const UNBOUND_HISTORY = { ...EMPTY_READING_HISTORY, loading: false };

/** Only the selected reading polls history; changing selection aborts all outstanding work. */
export function useReadingMonitoring(connection: SystemConnection | undefined, stream: SystemStream, savedBinding?: SystemReadingBinding, sharedCache?: ReadingHistoryCache) {
  const [localCache] = useState(() => new ReadingHistoryCache());
  const cache = sharedCache ?? localCache;
  const { id, topic, payload_pointer, value_type } = stream;
  const host = connection?.host, port = connection?.port, transport = connection?.transport, tls = connection?.tls;
  const entityId = savedBinding?.entity_id, telemetryType = savedBinding?.telemetry_key;
  const context = useMemo(() => host && port && transport && tls !== undefined ? {
    connection: { host, port, transport, tls },
    stream: { topic, payload_pointer, value_type },
    binding: entityId && telemetryType ? { entityId, telemetryType } : undefined,
    key: readingHistoryKey({ host, port, transport, tls }, { id, topic, payload_pointer, value_type }, entityId, telemetryType)!,
  } : undefined, [id, topic, payload_pointer, value_type, host, port, transport, tls, entityId, telemetryType]);
  const state = useReadingHistorySnapshot(cache, context?.key);

  useEffect(() => {
    if (!context) return;
    const controller = new AbortController();
    const { signal } = controller;
    let telemetryTimer: ReturnType<typeof setTimeout> | undefined;
    let monitoringTimer: ReturnType<typeof setTimeout> | undefined;
    let binding: ReadingMonitoringBinding | undefined;
    let telemetryPending = false;
    let monitoringPending = false;
    let telemetryFailed = false;
    let monitoringFailed = false;
    const previous = cache.get(context.key);
    // Returning after a long absence fetches the latest bounded page directly,
    // rather than paging through every observation received while away.
    const recent = (time?: number) => time !== undefined && Date.now() - time < 30_000;
    let telemetryCursor = recent(previous?.telemetryFetchedAt) ? previous?.telemetryCursor : undefined;
    let evidenceCursor = recent(previous?.evidenceFetchedAt) ? previous?.evidenceCursor : undefined;
    cache.touch(context.key);
    const error = () => telemetryFailed || monitoringFailed ? "Monitoring history could not be updated." : "";
    const get = <T,>(endpoint: string) => apiUtils.get<T>(endpoint, { signal, redirectOnUnauthorized: false });

    const loadTelemetry = async () => {
      const points: Array<TelemetryDataPoint & { created?: string }> = [];
      let cursor = telemetryCursor;
      for (let page = 0; page < 10; page++) {
        const incoming = await getTelemetryData(binding!.entityId, binding!.telemetryType, signal, cursor);
        points.push(...incoming);
        const next = getTelemetryCursor(incoming);
        if (!telemetryCursor || incoming.length < 1000 || !next || JSON.stringify(next) === JSON.stringify(cursor)) break;
        cursor = next;
      }
      return { points, cursor: getTelemetryCursor(points) ?? telemetryCursor };
    };
    const loadEvidence = async () => {
      const rows: MonitoringChartEvidence[] = [];
      let cursor = evidenceCursor;
      for (let page = 0; page < 10; page++) {
        const incoming = await get<MonitoringChartEvidence[]>(API_CONFIG.ENDPOINTS.MONITORING.CHART_EVIDENCE(binding!.entityId, cursor));
        rows.push(...incoming);
        const next = getMonitoringEvidenceCursor(incoming);
        if (!evidenceCursor || incoming.length < 2000 || !next || JSON.stringify(next) === JSON.stringify(cursor)) break;
        cursor = next;
      }
      return { rows, cursor: getMonitoringEvidenceCursor(rows) ?? evidenceCursor };
    };
    const pollTelemetry = async () => {
      if (!binding || telemetryPending || signal.aborted || document.hidden) return;
      clearTimeout(telemetryTimer);
      telemetryPending = true;
      try {
        const telemetry = await loadTelemetry();
        if (signal.aborted) return;
        telemetryCursor = telemetry.cursor;
        telemetryFailed = false;
        cache.update(context.key, entry => ({ ...entry, telemetryCursor, telemetryFetchedAt: Date.now(), data: {
          ...entry.data, binding, telemetry: telemetry.points.length ? mergeReadingHistory(entry.data.telemetry, telemetry.points) : entry.data.telemetry, loading: false, error: error(),
        } }));
      } catch {
        if (signal.aborted) return;
        telemetryFailed = true;
        cache.update(context.key, entry => ({ ...entry, data: { ...entry.data, binding, loading: false, error: error() } }));
      } finally { telemetryPending = false; }
      if (!signal.aborted) telemetryTimer = setTimeout(() => void pollTelemetry(), 2000);
    };
    const pollMonitoring = async () => {
      if (!binding || monitoringPending || signal.aborted || document.hidden) return;
      clearTimeout(monitoringTimer);
      monitoringPending = true;
      const [evidence, anomalies, services] = await Promise.allSettled([
        loadEvidence(),
        get<Anomaly[]>(API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(binding.entityId)),
        get<ActiveService[]>(`${API_CONFIG.ENDPOINTS.MONITORING.LIST}?active_only=false`),
      ]);
      monitoringPending = false;
      if (signal.aborted) return;
      if (evidence.status === "fulfilled") evidenceCursor = evidence.value.cursor;
      monitoringFailed = [evidence, anomalies, services].some(result => result.status === "rejected");
      const topic = savedBinding?.accepted_topic ?? buildDeviceTelemetryTopic(binding.entityId, binding.telemetryType);
      cache.update(context.key, entry => ({ ...entry, evidenceCursor,
        evidenceFetchedAt: evidence.status === "fulfilled" ? Date.now() : entry.evidenceFetchedAt,
        data: { ...entry.data, binding,
          evidence: evidence.status === "fulfilled" ? mergeMonitoringChartEvidence(entry.data.evidence, evidence.value.rows) : entry.data.evidence,
          anomalies: anomalies.status === "fulfilled" ? anomalies.value : entry.data.anomalies,
          services: services.status === "fulfilled" ? services.value.filter(service => (service.mqtt_topics ?? []).some(filter => mqttFiltersOverlap(filter, topic))) : entry.data.services,
          error: error(),
        },
      }));
      monitoringTimer = setTimeout(() => void pollMonitoring(), INTERVALS.DETAILS_UPDATE);
    };
    const connect = async () => {
      try {
        if (context.binding) binding = context.binding;

        if (binding) { void pollTelemetry(); void pollMonitoring(); }
        else cache.update(context.key, () => ({ data: { ...EMPTY_READING_HISTORY, loading: false } }));
      } catch {
        if (!signal.aborted) cache.update(context.key, entry => ({ ...entry, data: { ...entry.data, loading: false, error: "Monitoring history is unavailable." } }));
      }
    };
    const onVisibility = () => { if (!document.hidden) { void pollTelemetry(); void pollMonitoring(); } };
    document.addEventListener("visibilitychange", onVisibility);
    void connect();
    return () => {
      controller.abort();
      clearTimeout(telemetryTimer);
      clearTimeout(monitoringTimer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [context, cache, savedBinding?.accepted_topic]);
  return context ? state : UNBOUND_HISTORY;
}
