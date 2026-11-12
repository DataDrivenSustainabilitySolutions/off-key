import { useCallback, useEffect, useMemo, useState } from "react";
import { usePollingLoop } from "@/hooks/use-polling";
import { getTelemetryHistory } from "@/lib/charger-api";
import type { ReadingMonitoringBinding } from "@/domain/readings/readingMonitoring";
import type { HistoryPreference, TelemetryHistory } from "@/types/telemetry-history";
import { historyInterval } from "@/features/charts/history-presentation";

export const RANGE_PRESETS = [
  { id: "1h", label: "1h", title: "Last hour", spanMs: 3_600_000 },
  { id: "1d", label: "1d", title: "Last day", spanMs: 86_400_000 },
  { id: "7d", label: "7d", title: "Last 7 days", spanMs: 7 * 86_400_000 },
  { id: "all", label: "All", title: "All stored history", spanMs: undefined },
] as const;
export type RangePresetId = (typeof RANGE_PRESETS)[number]["id"];
export const rangePreset = (id: string) => RANGE_PRESETS.find((preset) => preset.id === id) ?? RANGE_PRESETS[0];

type Window = { startMs: number; endMs: number };
type Loaded = { scope: string; key: string; data?: TelemetryHistory; error?: string };
const DEFAULT_VIEW: HistoryPreference = { mode: "auto" };
const RETRY_MS = 5000, SLOWEST_REFRESH_MS = 60_000;

/**
 * A mean only changes as its interval fills, so the overview is asked again twice per
 * interval: every few seconds for the last hour, once a minute for a week. Original
 * samples and the whole history refresh each minute; the chart appends live values itself.
 */
export const overviewRefreshMs = (spanMs: number | undefined, { mode, windowMs }: HistoryPreference, buckets: number): number =>
  mode === "raw" || spanMs === undefined ? SLOWEST_REFRESH_MS
    : Math.min(SLOWEST_REFRESH_MS, Math.max(RETRY_MS, historyInterval(spanMs, buckets, windowMs) / 2));

/** Fetch original samples or real bucket statistics. Inspection freezes the overview. */
export function useStoredRange(binding: ReadingMonitoringBinding | undefined, spanMs: number | undefined,
  inspected?: Window, preference = DEFAULT_VIEW, buckets = 100) {
  const readingId = binding?.readingId;
  const scope = readingId ? JSON.stringify([readingId, spanMs ?? "all"]) : "";
  const { mode: view, windowMs } = preference;
  const key = JSON.stringify([scope, view, windowMs, buckets]);
  const startMs = inspected?.startMs, endMs = inspected?.endMs;
  const inspecting = inspected !== undefined;
  const detailKey = JSON.stringify([key, startMs, endMs]);
  const [overview, setOverview] = useState<Loaded>();
  const [detail, setDetail] = useState<Loaded>();

  const loadOverview = useCallback(async (signal: AbortSignal) => {
    if (!readingId) return;
    try {
      const data = await getTelemetryHistory(readingId, {
        startMs: spanMs === undefined ? undefined : Date.now() - spanMs,
        buckets, view, windowMs,
      }, signal);
      if (!signal.aborted) setOverview({ scope, key, data });
    } catch {
      if (!signal.aborted) setOverview(previous => ({ scope, key,
        data: previous?.key === key ? previous.data : undefined,
        error: "History could not be updated. Retrying automatically." }));
    }
  }, [readingId, spanMs, buckets, view, windowMs, scope, key]);
  const live = !!readingId && !inspected;
  usePollingLoop(loadOverview, { enabled: live, intervalMs: overviewRefreshMs(spanMs, preference, buckets),
    schedule: "after-completion", pauseWhenHidden: true, resumeOnVisible: true, startImmediately: true });
  // A failed request is asked again soon, whatever the refresh pace.
  usePollingLoop(loadOverview, { enabled: live && overview?.key === key && !!overview.error, intervalMs: RETRY_MS,
    schedule: "after-completion", pauseWhenHidden: true, initialRun: false });

  const loadDetail = useCallback(async (signal: AbortSignal) => {
    if (!readingId || startMs === undefined || endMs === undefined) return;
    try {
      const data = await getTelemetryHistory(readingId, { startMs, endMs, buckets, view, windowMs }, signal);
      if (!signal.aborted) setDetail({ scope, key: detailKey, data });
    } catch {
      if (!signal.aborted) setDetail(previous => ({ scope, key: detailKey,
        data: previous?.key === detailKey ? previous.data : undefined,
        error: "This interval could not be loaded. Retrying automatically." }));
    }
  }, [readingId, startMs, endMs, buckets, view, windowMs, scope, detailKey]);
  // Debounce drag events. An inspected window is fixed, so it loads once and is only
  // asked for again after a failed request.
  useEffect(() => {
    if (!readingId || !inspecting) return;
    const controller = new AbortController();
    const timer = setTimeout(() => { void loadDetail(controller.signal); }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [readingId, inspecting, loadDetail]);
  usePollingLoop(loadDetail, { enabled: !!readingId && inspecting && detail?.key === detailKey && !!detail.error,
    intervalMs: RETRY_MS, schedule: "after-completion", pauseWhenHidden: true, initialRun: false });

  return useMemo(() => {
    const selected = inspected ? detail?.key === detailKey ? detail : undefined : overview?.key === key ? overview : undefined;
    return { history: selected?.data, overview: overview?.scope === scope ? overview.data : undefined,
      loading: !!readingId && !selected, error: selected?.error ?? "" };
  }, [readingId, inspected, detail, detailKey, overview, key, scope]);
}
