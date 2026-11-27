import { epochMilliseconds, isoTimestamp } from "@/lib/timestamps";
import { useNow } from "@/hooks/use-now";
import { Fragment, useCallback, useMemo, useState, type KeyboardEvent } from "react";
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
import { buildDetectorInputSeries, withoutReadingCopies } from "@/features/charts/detector-inputs";
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
import { HistoryValues } from "@/features/charts/HistoryValues";
import { useHistoryWidth } from "@/features/charts/use-history-width";
import { combineHistory, DEFAULT_HISTORY_PREFERENCE, historyInterval, intervalLabel, presentHistory } from "@/features/charts/history-presentation";
import { summarizeDetection } from "@/features/charts/detection-summary";
import type { HistoryPreference } from "@/types/telemetry-history";
import { AnomalyStrip } from "@/features/charts/AnomalyStrip";
import { alarmSpans } from "@/features/charts/anomaly-strip";
import { MonitorViews, RAW_VIEW } from "@/features/charts/MonitorViews";
import { monitorColors } from "@/features/charts/monitor-colors";
import { CHART_INSETS } from "@/features/charts/telemetry-chart";
import { ChartKey } from "@/features/charts/ChartKey";

type Inspection = { startMs: number; endMs: number; windowStartMs: number };
type Props = { stream: SystemStream; connection?: SystemConnection; snapshot?: LiveNodeSnapshot; binding?: SystemReadingBinding; historyCache?: ReadingHistoryCache };

export function ExplorerHistoryChart({ stream, connection, snapshot, binding, historyCache }: Props) {
  const { resolvedTheme, colors } = useChartColors();
  const monitoring = useReadingMonitoring(connection, stream, binding, historyCache);
  const viewKey = historyCache ? `chart:${historyCache.owner}:${readingHistoryKey(connection, stream, binding)}` : undefined;
  const [rangeId, setRangeId] = useNavigationDraft<RangePresetId>(historyCache && `chart:${historyCache.owner}:range`, "1h");
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
    // A reading that went quiet before the range began has no stored points; what was
    // collected since still belongs on the chart.
    const last = stored.history.points[stored.history.points.length - 1];
    const lastMs = last ? epochMilliseconds(last.timestamp) : -Infinity;
    const tail = history.filter(point => epochMilliseconds(point.timestamp) > lastMs);
    if (!tail.length) return stored.history;
    return { ...stored.history, points: [...stored.history.points, ...tail], sample_count: stored.history.sample_count + tail.length,
      extent: [stored.history.extent?.[0] ?? tail[0]!.timestamp, tail[tail.length - 1]!.timestamp] as [string, string] };
  }, [stored.history, inspection, history]);
  // While a zoomed window or the other representation loads, the overview already on
  // screen stays, so the chart refines in place instead of blinking to live samples.
  const presentation = useMemo(() => currentHistory ? combineHistory(stored.overview, currentHistory, inspection)
    : stored.overview ?? (!monitoring.binding ? presentHistory(telemetry, numeric ? preference : { mode: "raw" }, buckets,
      inspection ? [inspection.startMs, inspection.endMs] : undefined) : undefined),
  [currentHistory, stored.overview, inspection, monitoring.binding, telemetry, numeric, preference, buckets]);
  const visibleHistory = currentHistory ?? presentation;
  const meanShown = visibleHistory?.representation === "mean";
  // A thinned raw view holds only some of the window's readings, like means hold none.
  const partial = meanShown || Boolean(visibleHistory?.column_ms);
  // Evidence and alarms name the catalogue reading the chart draws.
  const readingId = stream.id;
  // The chart shows the reading's raw data or one of its monitors. Until one is chosen, the first running monitor.
  const [chosenView, setView] = useNavigationDraft<string | undefined>(viewKey && `${viewKey}:view`, undefined);
  const service = useMemo(() => chosenView === RAW_VIEW ? undefined
    : monitoring.services.find(item => item.id === chosenView) ?? monitoring.services.find(item => item.active),
  [monitoring.services, chosenView]);
  const [aimed, setAimed] = useState<string>();
  const [gutter, setGutter] = useState<number>(CHART_INSETS.compact.left);
  const monitors = useMemo(() => {
    const colors = monitorColors(monitoring.services.map(item => item.id), resolvedTheme === "dark");
    return monitoring.services.map(item => ({ id: item.id, name: item.display_name || item.id, color: colors.get(item.id)! }));
  }, [monitoring.services, resolvedTheme]);
  // Raw data shows the reading alone; a monitor's view adds what that monitor recorded.
  const evidence = useMemo(() => !service && monitors.length ? [] : monitoring.evidence.filter((item) => item.reading_ids.includes(readingId)
    && (!service || item.monitor_id === service.id)), [monitoring.evidence, service, monitors.length, readingId]);
  // Raw data carries every monitor's anomalies on the strip; a monitor's view only its own.
  const stripRows = useMemo(() => {
    const results = new Map<string, Array<{ time: number; alarm: boolean }>>();
    for (const row of monitoring.evidence) {
      const time = getEvidenceTimeForSensor(row, readingId);
      if (time === undefined) continue;
      const own = results.get(row.monitor_id);
      if (own) own.push({ time, alarm: row.alarm });
      else results.set(row.monitor_id, [{ time, alarm: row.alarm }]);
    }
    return monitors.filter(monitor => !service || monitor.id === service.id)
      .map(monitor => ({ ...monitor, spans: alarmSpans(results.get(monitor.id) ?? []) }));
  }, [monitoring.evidence, readingId, monitors, service]);
  const anomalies = useMemo(() => filterServiceAnomalies(monitoring.anomalies, evidence, service?.id, readingId),
    [service?.id, monitoring.anomalies, evidence, readingId]);
  // Means and thinned readings stand for samples that are not loaded, so a detector result
  // cannot be matched to one. Every result of the window then counts: Auto shows the same detection as Raw.
  const telemetryTimes = useMemo(() => {
    const times = normalizedHistory.map(([time]) => time);
    if (!partial) return times;
    const scored = evidence.flatMap(row => { const time = getEvidenceTimeForSensor(row, readingId); return time === undefined ? [] : [time]; });
    return [...new Set([...times, ...scored])].sort((left, right) => left - right);
  }, [normalizedHistory, partial, evidence, readingId]);
  const detectionTimes = useMemo(() => partial ? telemetryTimes.filter(time => time >= cutoff) : undefined,
    [partial, telemetryTimes, cutoff]);
  const collectedTimes = useMemo(() => monitoring.telemetry.map((point) => epochMilliseconds(point.timestamp))
    .filter((time) => time >= cutoff), [monitoring.telemetry, cutoff]);
  const panes = useDetectorPanes({ telemetryType: readingId, evidence, telemetryTimes, pendingCandidateTimes: collectedTimes,
    service, selectionKey: `${stream.id}\u0000${service?.id ?? ""}` });
  const { detectors, selectedDetectorIds, pending } = panes;
  const detectorInputs = useMemo(() => {
    const first = meanShown ? cutoff : telemetry[0]?.[0], last = meanShown ? Infinity : telemetry[telemetry.length - 1]?.[0];
    return service && first !== undefined && last !== undefined
      ? withoutReadingCopies(buildDetectorInputSeries(evidence, row => getEvidenceTimeForSensor(row, readingId), [first, last]), normalizedHistory) : [];
  }, [service, evidence, readingId, telemetry, meanShown, cutoff, normalizedHistory]);
  const model = useMemo(() => buildTelemetryChartModel({
    telemetryName: stream.label, telemetryUnit: stream.unit, telemetryColor: colors.primary,
    telemetry, presentation, detectionTimes, detectors, selectedDetectorIds,
    pendingTelemetryTimestamps: pending, detectorInputs,
    anomalyMarkers: createAnomalyMarkers(history, filterAnomalies(anomalies, readingId, new Date(cutoff))),
  }), [readingId, stream.label, stream.unit, colors.primary, telemetry, presentation, detectionTimes, detectors,
    selectedDetectorIds, pending, detectorInputs, history, anomalies, cutoff]);
  // Stable between renders, so the inspect callback below is too.
  const extent = stored.overview?.extent;
  // The overview sets the historical bounds; samples appended since it loaded extend the live end.
  const domain = useMemo(() => {
    if (!extent) return getChartDomain(model.extent);
    const end = Math.max(epochMilliseconds(extent[1]), model.extent?.[1] ?? -Infinity);
    return getChartDomain([epochMilliseconds(extent[0]), end]);
  }, [extent, model.extent]);
  const resolution = visibleHistory?.representation === "mean" ? `${intervalLabel(visibleHistory.interval_ms)} mean · min–max` : "";
  const description = `${stream.label}. ${visibleHistory?.sample_count ?? model.telemetry.data.length} received samples. ${resolution ? `${resolution}. ` : ""}Times in ${timeZone}.`
    + (model.secondarySeries.length ? " Monitoring scores and thresholds share the time axis." : "");
  // Scores and features follow the reading into its intervals, each with the statistic it needs.
  const displayModel = useMemo(() => {
    if (viewPreference.mode === "raw") return model;
    const shown = inspection ? [inspection.startMs, inspection.endMs] as const : domain;
    const intervalMs = visibleHistory?.representation === "mean" ? visibleHistory.interval_ms
      : shown ? historyInterval(shown[1] - shown[0], buckets, viewPreference.windowMs) : 0;
    return summarizeDetection(model, intervalMs, buckets, shown);
  }, [model, viewPreference.mode, viewPreference.windowMs, inspection, domain, visibleHistory, buckets]);
  const option = useMemo(() => buildTelemetryChartOption({
    model: displayModel, viewport: inspection ? { mode: "absolute", startMs: inspection.startMs, endMs: inspection.endMs } : { mode: "live" },
    timeZone, colors, accessibleDescription: description, layout: "compact", timelineExtent: domain,
    valueType: stream.value_type === "boolean" ? "boolean" : "number",
  }), [displayModel, inspection, timeZone, colors, description, stream.value_type, domain]);
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
  const paneCount = 1 + Number(Boolean(model.detectorInputs?.some(series => !series.reading))) + Number(model.secondarySeries.some((item) => item.pane === "static"))
    + Number(model.secondarySeries.some((item) => item.pane === "adaptive"));
  const events = model.anomalyMarkers.filter((event) => !inspection
    || (event.timeMs >= inspection.startMs && event.timeMs <= inspection.endMs));

  const title = stream.value_type === "boolean" ? "State history" : "History";
  const hasValues = Boolean(presentation?.points.length || model.telemetry.data.length);
  return <section ref={chartWidthRef} className="ex-preview-history" aria-label={title}>
    <div className="ex-preview-section-heading">
      <h3>{title}</h3>
      <div className="ex-history-tools" role="group" aria-label="Chart controls">
        <MonitorViews monitors={monitors} value={service?.id ?? RAW_VIEW} onChange={setView} aimed={aimed} />
        {numeric && <HistoryViewControls value={preference} onChange={setPreference} intervalMs={visibleHistory?.interval_ms} />}
        <button type="button" aria-label="Zoom in" title="Zoom in" disabled={!domain} onClick={() => zoom(0.5)}><Plus size={15} /></button>
        <button type="button" aria-label="Zoom out" title="Zoom out" disabled={!inspection} onClick={() => zoom(2)}><Minus size={15} /></button>
        <button type="button" aria-label="Reset zoom" title="Reset zoom" disabled={!inspection} onClick={() => setInspection(undefined)}><RotateCcw size={14} /></button>
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
        onViewportChange={inspect} onGutter={setGutter} className={`ex-preview-chart ex-preview-chart--${paneCount}`} />
      {monitors.length > 0 && <AnomalyStrip rows={stripRows} domain={inspection ? [inspection.startMs, inspection.endMs] : domain}
        inset={{ ...CHART_INSETS.compact, left: gutter }} onPick={service ? undefined : setView} onAim={setAimed} />}
      {monitors.length > 0 && <p className="an-aimed" aria-hidden="true">{monitors.filter(monitor => monitor.id === aimed)
        .map(monitor => <Fragment key={monitor.id}><i style={{ background: monitor.color }} />{monitor.name}</Fragment>)}</p>}
    </div> : <div className="ex-preview-chart-empty" aria-busy={monitoring.loading || stored.loading || undefined}><Radio size={24} strokeWidth={1.3} /><strong>{monitoring.loading || stored.loading ? "Loading history…"
      : history.length ? "No values in selected range" : binding?.policy.mode !== undefined && binding.policy.mode !== "off" ? "Waiting for recorded values" : "Waiting for live values"}</strong></div>}
    {hasValues && model.secondarySeries.length > 0 && <ChartKey entries={[
      ...(model.detectorInputs?.some(series => series.reading) ? [{ kind: "observed" as const, label: "Observed", color: colors.primary },
        { kind: "forecast" as const, label: "Forecast" },
        { kind: "interval" as const, label: "Forecast interval" },
        { kind: "outside" as const, label: "Outside interval", color: colors.outsideInterval }] : []),
      { kind: "above", label: "Above threshold, no alarm", color: colors.foreground },
      ...(model.secondarySeries.some(series => series.data.some(point => point.observation?.alarmActive))
        ? [{ kind: "alarm" as const, label: "Alarm", color: colors.alarmBoundary }] : [])]} />}
    {model.secondarySeries.length > 0 && <TelemetryChartSummary model={model} timeZone={timeZone} showTelemetry={false} />}
    <TelemetryEventDetails groups={events} timeZone={timeZone} unit={stream.unit} />
    {hasValues && stored.loading && <p className="ex-preview-note" role="status">Loading {preference.mode === "raw" ? "raw readings" : "history"}…</p>}
    {!stored.loading && visibleHistory && visibleHistory.points.length > 0 && <HistoryValues key={visibleHistory.representation}
      history={visibleHistory} unit={stream.unit} />}
    {stored.error && <p className="ex-preview-note" role="status">{stored.error}</p>}
    {monitoring.error && <p className="ex-preview-note" role="status">{monitoring.error}</p>}
  </section>;
}
