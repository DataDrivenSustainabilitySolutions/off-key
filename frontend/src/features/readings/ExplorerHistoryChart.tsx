import { epochMilliseconds, isoTimestamp } from "@/lib/timestamps";
import { useNow } from "@/hooks/use-now";
import { useCallback, useMemo, type KeyboardEvent } from "react";
import { Minus, Plus, Radio, RotateCcw } from "lucide-react";
import { EChart } from "@/features/charts/EChart";
import { TelemetryChartSummary } from "@/features/charts/TelemetryChartSummary";
import { TelemetryDetectorControls } from "@/features/charts/TelemetryDetectorControls";
import { TelemetryEventDetails } from "@/features/charts/TelemetryEventDetails";
import { DetectorNotices } from "@/features/charts/DetectorNotices";
import { useChartColors } from "@/features/charts/use-chart-colors";
import { useDetectorPanes } from "@/features/charts/use-detector-panes";
import { createAnomalyMarkers, filterAnomalies } from "@/lib/anomaly-utils";
import { filterServiceAnomalies, getEvidenceTimeForSensor } from "@/lib/monitoring-chart";
import { buildDetectorInputSeries } from "@/features/charts/detector-inputs";
import { buildTelemetryChartModel, buildTelemetryChartOption, getLocalTimeZone } from "@/features/charts/telemetry-chart";
import { normalizeTelemetry } from "@/features/charts/telemetry-data";
import { getChartDomain } from "@/features/charts/telemetry-thresholds";
import type { LiveNodeSnapshot } from "@/types/system-live";
import type { SystemConnection, SystemStream, SystemReadingBinding } from "@/types/system";
import { useReadingMonitoring } from "./useReadingMonitoring";
import { RANGE_PRESETS, rangePreset, useStoredRange, type RangePresetId } from "./useStoredRange";
import { useNavigationDraft } from "@/lib/navigation-draft";
import { readingHistoryKey } from "@/domain/readings/readingHistoryCache";
import type { ReadingHistoryCache } from "@/domain/readings/readingHistoryCache";
import { HistoryViewControls } from "@/features/charts/HistoryViewControls";
import { RawHistoryValues } from "@/features/charts/RawHistoryValues";
import { useHistoryWidth } from "@/features/charts/use-history-width";
import { combineHistory, DEFAULT_HISTORY_PREFERENCE, intervalLabel, presentHistory } from "@/features/charts/history-presentation";
import type { HistoryPreference } from "@/types/telemetry-history";

type Inspection = { startMs: number; endMs: number; windowStartMs: number };
type Props = { stream: SystemStream; connection?: SystemConnection; snapshot?: LiveNodeSnapshot; binding?: SystemReadingBinding; historyCache?: ReadingHistoryCache };

export function ExplorerHistoryChart({ stream, connection, snapshot, binding, historyCache }: Props) {
  const { resolvedTheme, colors } = useChartColors();
  const monitoring = useReadingMonitoring(connection, stream, binding, historyCache);
  const viewKey = historyCache ? `chart:${historyCache.owner}:${readingHistoryKey(connection, stream, binding)}` : undefined;
  const [rangeId, setRangeId] = useNavigationDraft<RangePresetId>(viewKey && `${viewKey}:range`, "1h");
  const range = rangePreset(rangeId);
  const now = useNow(5000);
  const [inspection, setInspection] = useNavigationDraft<Inspection | undefined>(viewKey && `${viewKey}:inspection`, undefined);
  const [preference, setPreference] = useNavigationDraft<HistoryPreference>(viewKey && `${viewKey}:presentation`, DEFAULT_HISTORY_PREFERENCE);
  const numeric = stream.value_type !== "boolean";
  const viewPreference: HistoryPreference = numeric ? preference : { mode: "raw" };
  const { ref: chartWidthRef, buckets } = useHistoryWidth();
  const timeZone = useMemo(() => getLocalTimeZone(), []);
  const stored = useStoredRange(monitoring.binding, range.spanMs, inspection, viewPreference, buckets);

  const history = useMemo(() => {
    // Means are display-only; detector/alarm matching uses original samples.
    const originals = stored.history?.representation === "raw" ? stored.history.points : [];
    const lastStored = originals.length ? epochMilliseconds(originals[originals.length - 1]!.timestamp) : -Infinity;
    const collected = monitoring.telemetry.filter((point) => epochMilliseconds(point.timestamp) > lastStored);
    const lastCollected = collected.length ? epochMilliseconds(collected[collected.length - 1]!.timestamp) : lastStored;
    return [...originals, ...collected, ...(snapshot?.samples ?? [])
      .filter((sample) => sample.timestamp > lastCollected)
      .map((sample) => ({ timestamp: isoTimestamp(sample.timestamp), value: sample.value }))];
  }, [stored.history, monitoring.telemetry, snapshot?.samples]);
  const normalizedHistory = useMemo(() => normalizeTelemetry(history), [history]);
  const latestTime = Math.max(normalizedHistory[normalizedHistory.length - 1]?.[0] ?? 0,
    stored.overview?.extent ? epochMilliseconds(stored.overview.extent[1]) : 0) || now;
  // Quiet or stopped inputs still open at their latest real observations. The
  // timestamps remain unchanged; the window follows arrivals as they resume.
  const cutoff = inspection?.windowStartMs ?? (range.spanMs === undefined ? 0 : latestTime - range.spanMs);
  const telemetry = useMemo(() => normalizedHistory.filter(([time]) => time >= cutoff), [normalizedHistory, cutoff]);
  const currentHistory = useMemo(() => {
    if (!stored.history || stored.history.representation !== "raw" || inspection) return stored.history;
    const last = stored.history.points[stored.history.points.length - 1];
    const tail = last ? history.filter(point => epochMilliseconds(point.timestamp) > epochMilliseconds(last.timestamp)) : [];
    if (!tail.length) return stored.history;
    return { ...stored.history, points: [...stored.history.points, ...tail], sample_count: stored.history.sample_count + tail.length,
      extent: stored.history.extent ? [stored.history.extent[0], tail[tail.length - 1]!.timestamp] as [string, string] : null };
  }, [stored.history, inspection, history]);
  const presentation = useMemo(() => currentHistory ? combineHistory(stored.overview, currentHistory, inspection)
    : !monitoring.binding ? presentHistory(telemetry, numeric ? preference : { mode: "raw" }, buckets,
      inspection ? [inspection.startMs, inspection.endMs] : undefined) : undefined,
  [currentHistory, stored.overview, inspection, monitoring.binding, telemetry, numeric, preference, buckets]);
  const visibleHistory = currentHistory ?? presentation;
  // Evidence and alarms name the catalogue reading the chart draws.
  const readingId = stream.id;
  // The services already watch this reading; the first running one owns the chart.
  const service = useMemo(() => monitoring.services.find((item) => item.active), [monitoring.services]);
  const evidence = useMemo(() => monitoring.evidence.filter((item) => item.reading_ids.includes(readingId)
    && (!service || item.monitor_id === service.id)), [monitoring.evidence, service, readingId]);
  const anomalies = useMemo(() => filterServiceAnomalies(monitoring.anomalies, evidence, service?.id, readingId),
    [service?.id, monitoring.anomalies, evidence, readingId]);
  const telemetryTimes = useMemo(() => normalizedHistory.map(([time]) => time), [normalizedHistory]);
  const collectedTimes = useMemo(() => monitoring.telemetry.map((point) => epochMilliseconds(point.timestamp))
    .filter((time) => time >= cutoff), [monitoring.telemetry, cutoff]);
  const panes = useDetectorPanes({ telemetryType: readingId, evidence, telemetryTimes, pendingCandidateTimes: collectedTimes,
    service, selectionKey: `${stream.id}\u0000${service?.id ?? ""}` });
  const { detectors, selectedDetectorIds, pending } = panes;
  const detectorInputs = useMemo(() => {
    const first = telemetry[0]?.[0], last = telemetry[telemetry.length - 1]?.[0];
    return service && first !== undefined && last !== undefined
      ? buildDetectorInputSeries(evidence, row => getEvidenceTimeForSensor(row, readingId), [first, last]) : [];
  }, [service, evidence, readingId, telemetry]);
  const model = useMemo(() => buildTelemetryChartModel({
    telemetryName: stream.label, telemetryUnit: stream.unit, telemetryColor: colors.primary,
    telemetry, presentation, detectors, selectedDetectorIds,
    pendingTelemetryTimestamps: pending, detectorInputs,
    anomalyMarkers: createAnomalyMarkers(history, filterAnomalies(anomalies, readingId, new Date(cutoff))),
  }), [readingId, stream.label, stream.unit, colors.primary, telemetry, presentation, detectors,
    selectedDetectorIds, pending, detectorInputs, history, anomalies, cutoff]);
  // Stable between renders, so the inspect callback below is too.
  const extent = stored.overview?.extent;
  const domain = useMemo(() => getChartDomain(extent ? [epochMilliseconds(extent[0]), epochMilliseconds(extent[1])] : model.extent), [extent, model.extent]);
  const resolution = visibleHistory?.representation === "mean" ? `${intervalLabel(visibleHistory.interval_ms)} mean · min–max` : "";
  const description = `${stream.label}. ${visibleHistory?.sample_count ?? model.telemetry.data.length} received samples. ${resolution ? `${resolution}. ` : ""}Times in ${timeZone}.`
    + (model.secondarySeries.length ? " Monitoring scores and thresholds share the time axis." : "");
  const option = useMemo(() => buildTelemetryChartOption({
    model, viewport: inspection ? { mode: "absolute", startMs: inspection.startMs, endMs: inspection.endMs } : { mode: "live" },
    timeZone, colors, accessibleDescription: description, layout: "compact", timelineExtent: domain,
    valueType: stream.value_type === "boolean" ? "boolean" : "number",
  }), [model, inspection, timeZone, colors, description, stream.value_type, domain]);
  const inspect = useCallback((startMs: number, endMs: number) => {
    if (!domain || !Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return;
    const start = Math.max(domain[0], startMs);
    const end = Math.min(domain[1], endMs);
    if (end <= start) return;
    setInspection((current) => current && Math.abs(current.startMs - start) < 1 && Math.abs(current.endMs - end) < 1
      ? current : { startMs: start, endMs: end, windowStartMs: current?.windowStartMs ?? cutoff });
  }, [domain, cutoff, setInspection]);
  const zoom = (factor: number) => {
    if (!domain) return;
    const start = inspection?.startMs ?? domain[0];
    const end = inspection?.endMs ?? domain[1];
    const width = Math.min(domain[1] - domain[0], Math.max(1, (end - start) * factor));
    const nextStart = Math.max(domain[0], Math.min((start + end - width) / 2, domain[1] - width));
    inspect(nextStart, nextStart + width);
  };
  const navigate = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget || !domain) return;
    if (["+", "=", "-", "Home", "ArrowLeft", "ArrowRight"].includes(event.key)) event.preventDefault();
    if (event.key === "+" || event.key === "=") zoom(0.5);
    else if (event.key === "-") zoom(2);
    else if (event.key === "Home") setInspection(undefined);
    else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      const start = inspection?.startMs ?? domain[0];
      const end = inspection?.endMs ?? domain[1];
      const width = end - start;
      const delta = (event.key === "ArrowLeft" ? -1 : 1) * width * 0.2;
      const nextStart = Math.max(domain[0], Math.min(start + delta, domain[1] - width));
      inspect(nextStart, nextStart + width);
    }
  };
  const paneCount = 1 + Number(Boolean(model.detectorInputs?.length)) + Number(model.secondarySeries.some((item) => item.pane === "static"))
    + Number(model.secondarySeries.some((item) => item.pane === "adaptive"));
  const events = model.anomalyMarkers.filter((event) => !inspection
    || (event.timeMs >= inspection.startMs && event.timeMs <= inspection.endMs));

  const title = stream.value_type === "boolean" ? "State history" : "History";
  const hasValues = Boolean(presentation?.points.length || model.telemetry.data.length);
  return <section ref={chartWidthRef} className="ex-preview-history" aria-label={title}>
    <div className="ex-preview-section-heading">
      <h3>{title}</h3>
      <div className="ex-history-tools" role="group" aria-label="Chart controls">
        {numeric && <HistoryViewControls value={preference} onChange={setPreference} intervalMs={visibleHistory?.interval_ms} />}
        <button type="button" aria-label="Zoom in" title="Zoom in" disabled={!domain} onClick={() => zoom(0.5)}><Plus size={15} /></button>
        <button type="button" aria-label="Zoom out" title="Zoom out" disabled={!inspection} onClick={() => zoom(2)}><Minus size={15} /></button>
        <button type="button" disabled={!inspection} onClick={() => setInspection(undefined)}><RotateCcw size={13} /> Reset zoom</button>
        <div className="ex-history-ranges" role="group" aria-label="Chart time range">
          {RANGE_PRESETS.map((preset) => <button key={preset.id} type="button" title={preset.title}
            aria-pressed={preset.id === range.id} onClick={() => { setRangeId(preset.id); setInspection(undefined); }}>
            {preset.label}</button>)}
        </div>
      </div>
    </div>
    {service && <p className="ex-history-monitoring" role="status">{panes.awaitingFirstScore
      ? "Awaiting first score" : `Monitoring: ${service.operational_status.stage.replace(/_/g, " ")}`}
      {pending.length > 0 && ` · ${pending.length} awaiting score`}</p>}
    {evidence.some(row => row.reading_ids.length > 1) && <p className="ex-history-monitoring">Detector results describe the joint inputs; they do not attribute an alarm to this reading.</p>}
    {panes.showDetectorControls
      && <div className="ex-history-detectors"><TelemetryDetectorControls detectors={panes.controlCatalog} selected={selectedDetectorIds}
        unavailableIds={panes.unavailableIds} onSelect={panes.onSelect} /></div>}
    <DetectorNotices controlCatalog={panes.controlCatalog} selectedDetectorIds={selectedDetectorIds}
      unavailableIds={panes.unavailableIds} secondarySeries={model.secondarySeries} className="ex-preview-note" />
    {hasValues ? <div className="ex-history-navigation" role="group" aria-label="Chart navigation" tabIndex={0}
      onKeyDown={navigate}>
      <EChart option={option} resolvedTheme={resolvedTheme} accessibleDescription={description}
        onViewportChange={inspect} className={`ex-preview-chart ex-preview-chart--${paneCount}`} />
    </div> : <div className="ex-preview-chart-empty" aria-busy={monitoring.loading || stored.loading || undefined}><Radio size={24} strokeWidth={1.3} /><strong>{monitoring.loading || stored.loading ? "Loading history…"
      : history.length ? "No values in selected range" : binding?.policy.mode !== undefined && binding.policy.mode !== "off" ? "Waiting for recorded values" : "Waiting for live values"}</strong></div>}
    {model.secondarySeries.length > 0 && <TelemetryChartSummary model={model} timeZone={timeZone} showTelemetry={false} />}
    <TelemetryEventDetails groups={events} timeZone={timeZone} unit={stream.unit} />
    {hasValues && stored.loading && <p className="ex-preview-note" role="status">Loading {preference.mode === "raw" ? "raw readings" : "history"}…</p>}
    {visibleHistory?.truncated && <p className="ex-preview-note" role="status">Showing the latest {visibleHistory.points.length.toLocaleString()} of {visibleHistory.sample_count.toLocaleString()} raw readings in this range. Zoom in to inspect earlier readings.</p>}
    {preference.mode === "raw" && visibleHistory?.representation === "raw" && <RawHistoryValues points={visibleHistory.points} unit={stream.unit} />}
    {stored.error && <p className="ex-preview-note" role="status">{stored.error}</p>}
    {monitoring.error && <p className="ex-preview-note" role="status">{monitoring.error}</p>}
  </section>;
}
