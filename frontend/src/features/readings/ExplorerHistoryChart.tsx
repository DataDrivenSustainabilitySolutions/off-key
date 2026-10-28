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
import { filterServiceAnomalies } from "@/lib/monitoring-chart";
import { buildSensorClaims } from "@/lib/monitoring-services";
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

type Inspection = { startMs: number; endMs: number; windowStartMs: number };
type Props = { stream: SystemStream; connection?: SystemConnection; snapshot?: LiveNodeSnapshot; binding?: SystemReadingBinding; historyCache?: ReadingHistoryCache };

export function ExplorerHistoryChart({ stream, connection, snapshot, binding, historyCache }: Props) {
  const { resolvedTheme, colors } = useChartColors();
  const monitoring = useReadingMonitoring(connection, stream, binding, historyCache);
  const viewKey = historyCache ? `chart:${historyCache.owner}:${readingHistoryKey(connection, stream, binding?.entity_id, binding?.telemetry_key)}` : undefined;
  const [rangeId, setRangeId] = useNavigationDraft<RangePresetId>(viewKey && `${viewKey}:range`, "1h");
  const range = rangePreset(rangeId);
  const now = useNow(5000);
  const [inspection, setInspection] = useNavigationDraft<Inspection | undefined>(viewKey && `${viewKey}:inspection`, undefined);
  const timeZone = useMemo(() => getLocalTimeZone(), []);
  const stored = useStoredRange(monitoring.binding, range.spanMs, inspection);

  const history = useMemo(() => {
    const lastStored = stored.length ? Date.parse(stored[stored.length - 1]!.timestamp) : -Infinity;
    // Stored history is downsampled; collected timestamps are the actual detector
    // inputs; live arrivals extend both. Each source only adds what lies beyond
    // the one before it, rather than plotting the same value twice.
    const collected = monitoring.telemetry.filter((point) => Date.parse(point.timestamp) > lastStored);
    const lastCollected = collected.length ? Date.parse(collected[collected.length - 1]!.timestamp) : lastStored;
    return [...stored, ...collected, ...(snapshot?.samples ?? [])
      .filter((sample) => sample.timestamp > lastCollected)
      .map((sample) => ({ timestamp: new Date(sample.timestamp).toISOString(), value: sample.value }))];
  }, [stored, monitoring.telemetry, snapshot?.samples]);
  const normalizedHistory = useMemo(() => normalizeTelemetry(history), [history]);
  const latestTime = normalizedHistory[normalizedHistory.length - 1]?.[0] ?? now;
  // Quiet or stopped inputs still open at their latest real observations. The
  // timestamps remain unchanged; the window follows arrivals as they resume.
  const cutoff = inspection?.windowStartMs ?? (range.spanMs === undefined ? 0 : latestTime - range.spanMs);
  const telemetry = useMemo(() => normalizedHistory.filter(([time]) => time >= cutoff), [normalizedHistory, cutoff]);
  const telemetryType = monitoring.binding?.telemetryType ?? stream.id;
  const service = useMemo(() => monitoring.binding ? buildSensorClaims(monitoring.binding.entityId, [telemetryType],
    monitoring.services.filter((item) => item.status)).get(telemetryType) : undefined,
  [monitoring.binding, monitoring.services, telemetryType]);
  const evidence = useMemo(() => monitoring.evidence.filter((item) => item.sensor_set.includes(telemetryType)
    && (!service || item.service_id === service.id)), [monitoring.evidence, service, telemetryType]);
  const anomalies = useMemo(() => filterServiceAnomalies(monitoring.anomalies, evidence, service?.id, telemetryType),
    [service?.id, monitoring.anomalies, evidence, telemetryType]);
  const telemetryTimes = useMemo(() => normalizedHistory.map(([time]) => time), [normalizedHistory]);
  const collectedTimes = useMemo(() => monitoring.telemetry.map((point) => Date.parse(point.timestamp))
    .filter((time) => time >= cutoff), [monitoring.telemetry, cutoff]);
  const panes = useDetectorPanes({ telemetryType, evidence, telemetryTimes, pendingCandidateTimes: collectedTimes,
    service, selectionKey: `${stream.id}\u0000${service?.id ?? ""}` });
  const { detectors, selectedDetectorIds, pending } = panes;
  const model = useMemo(() => buildTelemetryChartModel({
    telemetryName: stream.label, telemetryUnit: stream.unit, telemetryColor: colors.primary,
    telemetry, detectors, selectedDetectorIds,
    pendingTelemetryTimestamps: pending,
    anomalyMarkers: createAnomalyMarkers(history, filterAnomalies(anomalies, telemetryType, new Date(cutoff))),
  }), [telemetryType, stream.label, stream.unit, colors.primary, telemetry, detectors,
    selectedDetectorIds, pending, history, anomalies, cutoff]);
  const domain = getChartDomain(model.extent);
  const description = `${stream.label}. ${model.telemetry.data.length} received samples. Times in ${timeZone}.`
    + (model.secondarySeries.length ? " Monitoring scores and thresholds share the time axis." : "");
  const option = useMemo(() => buildTelemetryChartOption({
    model, viewport: inspection ? { mode: "absolute", startMs: inspection.startMs, endMs: inspection.endMs } : { mode: "live" },
    timeZone, colors, accessibleDescription: description, layout: "compact",
    valueType: stream.value_type === "boolean" ? "boolean" : "number",
  }), [model, inspection, timeZone, colors, description, stream.value_type]);
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
  const paneCount = 1 + Number(model.secondarySeries.some((item) => item.pane === "static"))
    + Number(model.secondarySeries.some((item) => item.pane === "adaptive"));
  const events = model.anomalyMarkers.filter((event) => !inspection
    || (event.timeMs >= inspection.startMs && event.timeMs <= inspection.endMs));

  return <section className="ex-preview-history" aria-label="Live history">
    <div className="ex-preview-section-heading">
      <h3>{stream.value_type === "boolean" ? "State history" : "Live history"}</h3>
      <div className="ex-history-tools" role="group" aria-label="Chart controls">
        <button type="button" aria-label="Zoom in" title="Zoom in" disabled={model.telemetry.data.length < 2} onClick={() => zoom(0.5)}><Plus size={15} /></button>
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
    {evidence.some(row => row.sensor_set.length > 1) && <p className="ex-history-monitoring">Detector results describe the joint inputs; they do not attribute an alarm to this reading.</p>}
    {panes.showDetectorControls
      && <div className="ex-history-detectors"><TelemetryDetectorControls detectors={panes.controlCatalog} selected={selectedDetectorIds}
        unavailableIds={panes.unavailableIds} onSelect={panes.onSelect} /></div>}
    <DetectorNotices controlCatalog={panes.controlCatalog} selectedDetectorIds={selectedDetectorIds}
      unavailableIds={panes.unavailableIds} secondarySeries={model.secondarySeries} className="ex-preview-note" />
    {model.telemetry.data.length ? <div className="ex-history-navigation" role="group" aria-label="Chart navigation" tabIndex={0}
      onKeyDown={navigate}>
      <EChart option={option} resolvedTheme={resolvedTheme} accessibleDescription={description}
        onViewportChange={inspect} className={`ex-preview-chart ex-preview-chart--${paneCount}`} />
    </div> : <div className="ex-preview-chart-empty" aria-busy={monitoring.loading || undefined}><Radio size={24} strokeWidth={1.3} /><strong>{monitoring.loading ? "Loading history…"
      : history.length ? "No values in selected range" : binding?.policy.mode !== undefined && binding.policy.mode !== "off" ? "Waiting for recorded values" : "Waiting for live values"}</strong></div>}
    {model.secondarySeries.length > 0 && <TelemetryChartSummary model={model} timeZone={timeZone} showTelemetry={false} />}
    <TelemetryEventDetails groups={events} timeZone={timeZone} unit={stream.unit} />
    {monitoring.error && <p className="ex-preview-note" role="status">{monitoring.error}</p>}
  </section>;
}
