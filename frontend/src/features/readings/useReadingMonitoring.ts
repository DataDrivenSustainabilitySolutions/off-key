import { useEffect, useMemo, useState } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { drainForward, EVIDENCE_PAGE_SIZE, TELEMETRY_PAGE_SIZE } from "@/lib/forward-pages";
import { getTelemetryCursor, getTelemetryData } from "@/lib/charger-api";
import { INTERVALS } from "@/lib/constants";
import { buildDeviceTelemetryTopic } from "@/lib/mqtt-topics";
import { mqttFiltersOverlap } from "@/lib/monitoring-services";
import { getMonitoringEvidenceCursor, mergeMonitoringChartEvidence } from "@/lib/monitoring-chart";
import type { Anomaly } from "@/types/charger";
import type { MonitoringChartEvidence } from "@/types/monitoring";
import { useMonitoringServices } from "@/domain/monitoring/useMonitoringServices";
import type { SystemConnection, SystemStream, SystemReadingBinding } from "@/types/system";
import { mergeReadingHistory, type ReadingMonitoringBinding } from "@/domain/readings/readingMonitoring";
import { EMPTY_READING_HISTORY, ReadingHistoryCache, readingHistoryKey, useReadingHistorySnapshot } from "@/domain/readings/readingHistoryCache";
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
      const points = await drainForward({
        cursor: telemetryCursor,
        fetchPage: cursor => getTelemetryData(binding!.entityId, binding!.telemetryType, signal, cursor),
        cursorOf: getTelemetryCursor,
        pageSize: TELEMETRY_PAGE_SIZE,
      });
      return { points, cursor: getTelemetryCursor(points) ?? telemetryCursor };
    };
    const loadEvidence = async () => {
      const rows = await drainForward({
        cursor: evidenceCursor,
        fetchPage: cursor => get<MonitoringChartEvidence[]>(API_CONFIG.ENDPOINTS.MONITORING.CHART_EVIDENCE(binding!.entityId, cursor)),
        cursorOf: getMonitoringEvidenceCursor,
        pageSize: EVIDENCE_PAGE_SIZE,
      });
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
      const [evidence, anomalies] = await Promise.allSettled([
        loadEvidence(),
        get<Anomaly[]>(API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(binding.entityId)),
      ]);
      monitoringPending = false;
      if (signal.aborted) return;
      if (evidence.status === "fulfilled") evidenceCursor = evidence.value.cursor;
      monitoringFailed = [evidence, anomalies].some(result => result.status === "rejected");
      cache.update(context.key, entry => ({ ...entry, evidenceCursor,
        evidenceFetchedAt: evidence.status === "fulfilled" ? Date.now() : entry.evidenceFetchedAt,
        data: { ...entry.data, binding,
          evidence: evidence.status === "fulfilled" ? mergeMonitoringChartEvidence(entry.data.evidence, evidence.value.rows) : entry.data.evidence,
          anomalies: anomalies.status === "fulfilled" ? anomalies.value : entry.data.anomalies,
          error: error(),
        },
      }));
      monitoringTimer = setTimeout(() => void pollMonitoring(), INTERVALS.DETAILS_UPDATE);
    };
    const connect = () => {
      if (context.binding) binding = context.binding;
      if (binding) { void pollTelemetry(); void pollMonitoring(); }
      else cache.update(context.key, () => ({ data: { ...EMPTY_READING_HISTORY, loading: false } }));
    };
    const onVisibility = () => { if (!document.hidden) { void pollTelemetry(); void pollMonitoring(); } };
    document.addEventListener("visibilitychange", onVisibility);
    connect();
    return () => {
      controller.abort();
      clearTimeout(telemetryTimer);
      clearTimeout(monitoringTimer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [context, cache]);
  // The service list comes from the workspace's shared poll, filtered to this reading's topic.
  const feed = useMonitoringServices(!!context?.binding, INTERVALS.DETAILS_UPDATE);
  const acceptedTopic = savedBinding?.accepted_topic;
  const services = useMemo(() => {
    if (!context?.binding) return [];
    const topic = acceptedTopic ?? buildDeviceTelemetryTopic(context.binding.entityId, context.binding.telemetryType);
    return feed.services.filter(service => (service.mqtt_topics ?? []).some(filter => mqttFiltersOverlap(filter, topic)));
  }, [context, acceptedTopic, feed.services]);
  const history = context ? state : UNBOUND_HISTORY;
  return { ...history, services, error: history.error || (context?.binding && feed.error ? "Monitoring services could not be updated." : "") };
}
