import { useCallback, useEffect, useMemo, useState } from "react";
import { usePollingLoop } from "@/hooks/use-polling";
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
// Returning after a long absence fetches the latest bounded page directly,
// rather than paging through every observation received while away.
const recent = (time?: number) => time !== undefined && Date.now() - time < 30_000;

/** The cursors and failure state of one selected reading's two history loops. */
class ReadingPolls {
  private telemetryCursor;
  private evidenceCursor;
  private telemetryFailed = false;
  private monitoringFailed = false;

  constructor(private readonly cache: ReadingHistoryCache, private readonly key: string, readonly binding: ReadingMonitoringBinding) {
    const previous = cache.get(key);
    this.telemetryCursor = recent(previous?.telemetryFetchedAt) ? previous?.telemetryCursor : undefined;
    this.evidenceCursor = recent(previous?.evidenceFetchedAt) ? previous?.evidenceCursor : undefined;
  }

  private error() {
    return this.telemetryFailed || this.monitoringFailed ? "Monitoring history could not be updated." : "";
  }

  async telemetry(signal: AbortSignal) {
    const { binding } = this;
    try {
      const points = await drainForward({
        cursor: this.telemetryCursor,
        fetchPage: cursor => getTelemetryData(binding.entityId, binding.telemetryType, signal, cursor),
        cursorOf: getTelemetryCursor,
        pageSize: TELEMETRY_PAGE_SIZE,
      });
      if (signal.aborted) return;
      this.telemetryCursor = getTelemetryCursor(points) ?? this.telemetryCursor;
      this.telemetryFailed = false;
      const telemetryCursor = this.telemetryCursor;
      this.cache.update(this.key, entry => ({ ...entry, telemetryCursor, telemetryFetchedAt: Date.now(), data: {
        ...entry.data, binding, telemetry: points.length ? mergeReadingHistory(entry.data.telemetry, points) : entry.data.telemetry, loading: false, error: this.error(),
      } }));
    } catch {
      if (signal.aborted) return;
      this.telemetryFailed = true;
      this.cache.update(this.key, entry => ({ ...entry, data: { ...entry.data, binding, loading: false, error: this.error() } }));
    }
  }

  async monitoring(signal: AbortSignal) {
    const { binding } = this;
    const get = <T,>(endpoint: string) => apiUtils.get<T>(endpoint, { signal, redirectOnUnauthorized: false });
    const [evidence, anomalies] = await Promise.allSettled([
      drainForward({
        cursor: this.evidenceCursor,
        fetchPage: cursor => get<MonitoringChartEvidence[]>(API_CONFIG.ENDPOINTS.MONITORING.CHART_EVIDENCE(binding.entityId, cursor)),
        cursorOf: getMonitoringEvidenceCursor,
        pageSize: EVIDENCE_PAGE_SIZE,
      }),
      get<Anomaly[]>(API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(binding.entityId)),
    ]);
    if (signal.aborted) return;
    if (evidence.status === "fulfilled") this.evidenceCursor = getMonitoringEvidenceCursor(evidence.value) ?? this.evidenceCursor;
    this.monitoringFailed = [evidence, anomalies].some(result => result.status === "rejected");
    const evidenceCursor = this.evidenceCursor;
    this.cache.update(this.key, entry => ({ ...entry, evidenceCursor,
      evidenceFetchedAt: evidence.status === "fulfilled" ? Date.now() : entry.evidenceFetchedAt,
      data: { ...entry.data, binding,
        evidence: evidence.status === "fulfilled" ? mergeMonitoringChartEvidence(entry.data.evidence, evidence.value) : entry.data.evidence,
        anomalies: anomalies.status === "fulfilled" ? anomalies.value : entry.data.anomalies,
        error: this.error(),
      },
    }));
  }
}
const LOOP = { overlap: "skip", schedule: "after-completion", pauseWhenHidden: true, resumeOnVisible: true, startImmediately: true } as const;

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

  const polls = useMemo(() => context?.binding && new ReadingPolls(cache, context.key, context.binding), [cache, context]);
  useEffect(() => {
    if (!context) return;
    cache.touch(context.key);
    if (!context.binding) cache.update(context.key, () => ({ data: { ...UNBOUND_HISTORY } }));
  }, [cache, context]);
  const pollTelemetry = useCallback((signal: AbortSignal) => polls?.telemetry(signal), [polls]);
  const pollMonitoring = useCallback((signal: AbortSignal) => polls?.monitoring(signal), [polls]);
  usePollingLoop(pollTelemetry, { ...LOOP, enabled: !!polls, intervalMs: 2000 });
  usePollingLoop(pollMonitoring, { ...LOOP, enabled: !!polls, intervalMs: INTERVALS.DETAILS_UPDATE });
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
