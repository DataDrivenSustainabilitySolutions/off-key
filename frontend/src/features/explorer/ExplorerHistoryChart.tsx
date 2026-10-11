import { useCallback, useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { Minus, Plus, Radio, RotateCcw } from "lucide-react";
import { EChart } from "@/components/EChart";
import { TelemetryChartSummary } from "@/components/TelemetryChartSummary";
import { TelemetryDetectorControls } from "@/components/TelemetryDetectorControls";
import { TelemetryEventDetails } from "@/components/TelemetryEventDetails";
import { useTheme } from "@/components/theme-provider";
import { useDetectorSelection } from "@/hooks/use-detector-selection";
import { createAnomalyMarkers, filterAnomalies } from "@/lib/anomaly-utils";
import { resolveChartThemeColors } from "@/lib/echarts-theme";
import { getEvidenceTimeForSensor } from "@/lib/monitoring-chart";
import { buildSensorClaims } from "@/lib/monitoring-services";
import { buildTelemetryChartModel, buildTelemetryChartOption, getLocalTimeZone } from "@/lib/telemetry-chart";
import { getChartDomain } from "@/lib/telemetry-thresholds";
import type { LiveNodeSnapshot } from "../spatial/systemLiveTypes";
import type { SystemConnection, SystemStream, SystemReadingBinding } from "../spatial/systemTypes";
import { useReadingMonitoring } from "./useReadingMonitoring";
import type { ReadingHistoryCache } from "./readingHistoryCache";

type Inspection = { startMs: number; endMs: number; windowStartMs: number };
type Props = { stream: SystemStream; connection?: SystemConnection; snapshot?: LiveNodeSnapshot; binding?: SystemReadingBinding; serviceId?: string; historyCache?: ReadingHistoryCache };

export function ExplorerHistoryChart({ stream, connection, snapshot, binding, serviceId, historyCache }: Props) {
  const { resolvedTheme } = useTheme();
  const monitoring = useReadingMonitoring(connection, stream, binding, historyCache);
  const [minutes, setMinutes] = useState(15);
  const [now, setNow] = useState(Date.now);
  const [inspection, setInspection] = useState<Inspection>();
  const timeZone = useMemo(() => getLocalTimeZone(), []);
  const colors = useMemo(() => resolveChartThemeColors(resolvedTheme), [resolvedTheme]);
  useEffect(() => {
    const timer = setInterval(() => { if (!document.hidden) setNow(Date.now()); }, 5000);
    return () => clearInterval(timer);
  }, []);

  const history = useMemo(() => {
    const collected = monitoring.telemetry;
    const lastCollected = collected.length ? Date.parse(collected[collected.length - 1]!.timestamp) : -Infinity;
    // Collected timestamps are the actual detector inputs. Use live arrivals only
    // beyond the collected history, rather than plotting the same value twice.
    return [...collected, ...(snapshot?.samples ?? [])
      .filter((sample) => sample.timestamp > lastCollected)
      .map((sample) => ({ timestamp: new Date(sample.timestamp).toISOString(), value: sample.value }))];
  }, [monitoring.telemetry, snapshot?.samples]);
  const latestTime = history.length ? Date.parse(history[history.length - 1]!.timestamp) : now;
  // Quiet or stopped inputs still open at their latest real observations. The
  // timestamps remain unchanged; the window follows arrivals as they resume.
  const cutoff = inspection?.windowStartMs ?? latestTime - minutes * 60_000;
  const telemetry = useMemo(() => history.filter((point) => Date.parse(point.timestamp) >= cutoff), [history, cutoff]);
  const telemetryType = monitoring.binding?.telemetryType ?? stream.id;
  const service = useMemo(() => serviceId ? monitoring.services.find(item => item.id === serviceId) : monitoring.binding ? buildSensorClaims(monitoring.binding.entityId, [telemetryType],
    monitoring.services.filter((item) => item.status)).get(telemetryType) : undefined,
  [monitoring.binding, monitoring.services, telemetryType, serviceId]);
  const evidence = useMemo(() => monitoring.evidence.filter((item) => item.sensor_set.includes(telemetryType)
    && (!(serviceId ?? service?.id) || item.service_id === (serviceId ?? service?.id))), [monitoring.evidence, service, telemetryType, serviceId]);
  const anomalies = useMemo(() => {
    if (!serviceId) return monitoring.anomalies;
    // Legacy anomaly rows have no service ID. Only attach events corroborated by
    // this service's alarm evidence when inspecting a particular monitor.
    const times = new Set(evidence.filter(item => item.alarm).flatMap(item => [Date.parse(item.timestamp), getEvidenceTimeForSensor(item, telemetryType)]));
    return monitoring.anomalies.filter(item => times.has(Date.parse(item.timestamp)));
  }, [serviceId, monitoring.anomalies, evidence, telemetryType]);
  const operational = service?.operational_status.stage === "operational" && !service.operational_status.is_stale;
  const lastScoreTime = evidence.reduce<number | undefined>((latest, item) => {
    const time = getEvidenceTimeForSensor(item, telemetryType);
    return time === undefined ? latest : Math.max(latest ?? -Infinity, time);
  }, undefined);
  const pending = useMemo(() => operational && lastScoreTime !== undefined ? monitoring.telemetry
    .map((point) => Date.parse(point.timestamp)).filter((time) => time >= cutoff && time > lastScoreTime) : [],
  [operational, lastScoreTime, monitoring.telemetry, cutoff]);
  const detectorCatalog = useMemo(() => buildTelemetryChartModel({
    telemetryType, telemetryName: stream.label, telemetryColor: colors.primary,
    telemetry: history, evidence, anomalyZones: [], anomalyMarkers: [],
  }).detectors, [telemetryType, stream.label, colors.primary, history, evidence]);
  const selection = useDetectorSelection(detectorCatalog, `${stream.id}\u0000${service?.id ?? ""}`);
  const selectedDetectorIds = useMemo(() => ({
    static: selection.selectedDetectorIds.static, adaptive: selection.selectedDetectorIds.adaptive,
  }), [selection.selectedDetectorIds.static, selection.selectedDetectorIds.adaptive]);
  const model = useMemo(() => buildTelemetryChartModel({
    telemetryType, telemetryName: stream.label, telemetryUnit: stream.unit, telemetryColor: colors.primary,
    telemetry, evidence, selectedDetectorIds,
    pendingTelemetryTimestamps: pending, anomalyZones: [],
    anomalyMarkers: createAnomalyMarkers(history, filterAnomalies(anomalies, telemetryType, new Date(cutoff))),
  }), [telemetryType, stream.label, stream.unit, colors.primary, telemetry, evidence,
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
  }, [domain, cutoff]);
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
        <button type="button" disabled={!inspection} onClick={() => setInspection(undefined)}><RotateCcw size={13} /> Full range</button>
        <select aria-label="Live chart time range" value={minutes} onChange={(event) => {
          setMinutes(Number(event.target.value)); setInspection(undefined);
        }}><option value={5}>5 minutes</option><option value={15}>15 minutes</option>
          <option value={60}>1 hour</option><option value={120}>2 hours</option></select>
      </div>
    </div>
    {service && <p className="ex-history-monitoring" role="status">{operational && lastScoreTime === undefined
      ? "Awaiting first score" : `Monitoring: ${service.operational_status.stage.replace(/_/g, " ")}`}
      {pending.length > 0 && ` · ${pending.length} awaiting score`}</p>}
    {selection.controlCatalog.some((detector) => selection.controlCatalog.filter((item) => item.pane === detector.pane).length > 1)
      && <div className="ex-history-detectors"><TelemetryDetectorControls detectors={selection.controlCatalog} selected={selection.selectedDetectorIds}
        unavailableIds={selection.unavailableIds} onSelect={selection.onSelect} /></div>}
    {selection.controlCatalog.filter((detector) => detector.id === selectedDetectorIds[detector.pane]
      && !model.secondarySeries.some((series) => series.id === detector.id)).map((detector) =>
      <p key={detector.id} className="ex-preview-note" role="status">{detector.name}: {selection.unavailableIds.has(detector.id)
        ? "No evaluated observations available" : "No evaluated observations in selected range"}</p>)}
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
