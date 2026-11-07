import { epochMilliseconds } from "@/lib/timestamps";
import { useCallback, useEffect, useMemo, useState } from "react";
import { usePollingLoop } from "@/hooks/use-polling";
import { getTelemetryRange } from "@/lib/charger-api";
import type { ReadingMonitoringBinding } from "@/domain/readings/readingMonitoring";
import type { TelemetryDataPoint } from "@/types/charger";

export const RANGE_PRESETS = [
  { id: "1h", label: "1h", title: "Last hour", spanMs: 3_600_000 },
  { id: "1d", label: "1d", title: "Last day", spanMs: 86_400_000 },
  { id: "7d", label: "7d", title: "Last 7 days", spanMs: 7 * 86_400_000 },
  { id: "all", label: "All", title: "All stored history", spanMs: undefined },
] as const;
export type RangePresetId = (typeof RANGE_PRESETS)[number]["id"];
export const rangePreset = (id: string) => RANGE_PRESETS.find((preset) => preset.id === id) ?? RANGE_PRESETS[0];

/** Points per request: each bucket returns its lowest and highest value, so at most twice this. */
const RANGE_BUCKETS = 600;
const OVERVIEW_REFRESH_MS = 60_000;
const DETAIL_DELAY_MS = 250;

type Window = { startMs: number; endMs: number };
type Loaded = { key: string; points: TelemetryDataPoint[] };

/**
 * Stored history for a recorded reading: a downsampled overview of the chosen
 * span, refreshed each minute, and a finer fetch of the window being inspected,
 * so zooming in recovers detail the overview's buckets summarised.
 */
export function useStoredRange(binding: ReadingMonitoringBinding | undefined, spanMs: number | undefined, inspected?: Window) {
  const readingId = binding?.readingId;
  const overviewKey = readingId ? JSON.stringify([readingId, spanMs ?? "all"]) : undefined;
  const [overview, setOverview] = useState<Loaded>();
  const [detail, setDetail] = useState<Loaded & Window>();

  const loadOverview = useCallback(async (signal: AbortSignal) => {
    if (!overviewKey || !readingId) return;
    try {
      const points = await getTelemetryRange(readingId,
        { startMs: spanMs === undefined ? undefined : Date.now() - spanMs, buckets: RANGE_BUCKETS }, signal);
      if (!signal.aborted) setOverview({ key: overviewKey, points });
    } catch {
      // Live and recently collected values still draw; the next refresh retries.
    }
  }, [overviewKey, readingId, spanMs]);
  usePollingLoop(loadOverview, { enabled: !!overviewKey, intervalMs: OVERVIEW_REFRESH_MS, schedule: "after-completion",
    pauseWhenHidden: true, resumeOnVisible: true, startImmediately: true });

  const startMs = inspected?.startMs, endMs = inspected?.endMs;
  useEffect(() => {
    if (!overviewKey || !readingId || startMs === undefined || endMs === undefined) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      getTelemetryRange(readingId, { startMs, endMs, buckets: RANGE_BUCKETS }, controller.signal)
        .then((points) => { if (!controller.signal.aborted) setDetail({ key: overviewKey, startMs, endMs, points }); })
        .catch(() => {});
    }, DETAIL_DELAY_MS);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [overviewKey, readingId, startMs, endMs]);

  return useMemo(() => {
    const base = overview && overview.key === overviewKey ? overview.points : [];
    if (!detail || detail.key !== overviewKey || startMs === undefined) return base;
    // The finer points replace the overview only across the window they cover.
    const inside = (point: TelemetryDataPoint) => {
      const time = epochMilliseconds(point.timestamp);
      return time >= detail.startMs && time <= detail.endMs;
    };
    return [...base.filter((point) => !inside(point)), ...detail.points]
      .sort((left, right) => epochMilliseconds(left.timestamp) - epochMilliseconds(right.timestamp));
  }, [overview, detail, overviewKey, startMs]);
}
