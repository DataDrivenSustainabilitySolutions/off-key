import { useCallback, useMemo, type KeyboardEvent } from "react";
import { Minus, Plus, RotateCcw } from "lucide-react";
import { EChart } from "@/features/charts/EChart";
import { TelemetryDetectorControls } from "@/features/charts/TelemetryDetectorControls";
import { useChartColors } from "@/features/charts/use-chart-colors";
import { useDetectorSelection } from "@/features/charts/use-detector-selection";
import { useNavigationDraft } from "@/lib/navigation-draft";
import { buildMonitoringChartOption, formatChartTime, formatNumber, getLocalTimeZone } from "@/features/charts/telemetry-chart";
import { getChartDomain } from "@/features/charts/telemetry-thresholds";
import type { ActiveService } from "@/types/monitoring";
import type { SystemConnection } from "@/types/system";
import type { ReadingHistoryCache } from "@/domain/readings/readingHistoryCache";
import type { MonitoringInput } from "@/domain/monitoring/serviceModel";
import { buildServiceHistoryModel, MAX_VISIBLE_READINGS } from "./historyModel";
import { useServiceHistory } from "./useServiceHistory";
import { useHistoryPresentation } from "./useHistoryPresentation";
import { ForecastControls } from "./ForecastControls";
import { forecastLeadKey } from "@/features/charts/forecast-evidence";
import { FORECAST_VIEW_LABELS, type ForecastView } from "@/features/charts/forecast-future";
import { ForecastViewButton } from "./ForecastViewButton";

type Inspection = { startMs: number; endMs: number };

export function MonitoringHistory({ service, inputs, connections, historyCache, initialReading }: {
  service: ActiveService; inputs: MonitoringInput[]; connections: SystemConnection[];
  historyCache?: ReadingHistoryCache; initialReading?: string;
}) {
  const { resolvedTheme, colors } = useChartColors();
  const key = `monitoring-chart:${historyCache?.owner ?? "local"}:${service.id}:${initialReading ?? "all"}`;
  const [chosen, setChosen] = useNavigationDraft<string[]>(`${key}:readings`,
    initialReading ? [initialReading] : inputs.slice(0, MAX_VISIBLE_READINGS).map(input => input.stream.id));
  const [inspection, setInspection] = useNavigationDraft<Inspection | undefined>(`${key}:inspection`, undefined);
  const [chosenLead, setChosenLead] = useNavigationDraft<string>(`${key}:lead`, "");
  const [showScores, setShowScores] = useNavigationDraft<boolean>(`${key}:scores`, false);
  const [forecastView, setForecastView] = useNavigationDraft<ForecastView>(`${key}:forecast-view`, "overlay");
  const [showResiduals, setShowResiduals] = useNavigationDraft<boolean>(`${key}:residuals`, true);
  const presentation = useHistoryPresentation(service.id);
  const selectedInputs = useMemo(() => {
    const retained = inputs.filter(input => chosen.includes(input.stream.id)).slice(0, MAX_VISIBLE_READINGS);
    return retained.length ? retained : inputs.slice(0, MAX_VISIBLE_READINGS);
  }, [inputs, chosen]);
  const history = useServiceHistory(service.id, selectedInputs, inputs, connections, historyCache);
  const timeZone = useMemo(() => getLocalTimeZone(), []);
  const histories = useMemo(() => new Map([...history.histories].map(([id, value]) => [id, value.telemetry])), [history.histories]);
  const operational = service.active && service.operational_status.stage === "operational" && !service.operational_status.is_stale;
  const base = useMemo(() => buildServiceHistoryModel({ serviceId: service.id, inputs: selectedInputs, allInputs: inputs,
    histories, evidence: history.monitoring.evidence, dark: resolvedTheme === "dark", operational, presentation: presentation.presentation }),
  [service.id, selectedInputs, inputs, histories, history.monitoring.evidence, resolvedTheme, operational, presentation.presentation]);
  const selection = useDetectorSelection(base.detectors, service.id);
  const { model: completeModel } = useMemo(() => buildServiceHistoryModel({ serviceId: service.id, inputs: selectedInputs, allInputs: inputs,
    histories, evidence: history.monitoring.evidence, dark: resolvedTheme === "dark", selectedDetectorIds: selection.selectedDetectorIds, operational, presentation: presentation.presentation }),
  [service.id, selectedInputs, inputs, histories, history.monitoring.evidence, resolvedTheme, selection.selectedDetectorIds, operational, presentation.presentation]);
  const forecasts = completeModel.forecasts ?? [];
  const lead = forecasts.some(forecast => forecastLeadKey(forecast.lead) === chosenLead) ? chosenLead : forecastLeadKey(forecasts[0]?.lead ?? null);
  const intervalLabel = presentation.presentation?.intervalLabel ?? "Calibrated interval";
  const model = useMemo(() => ({ ...completeModel, intervalLabel, forecastView, showResiduals,
    forecasts: completeModel.forecasts?.filter(forecast => forecastLeadKey(forecast.lead) === lead),
    secondarySeries: completeModel.forecasts?.length && !showScores ? [] : completeModel.secondarySeries,
  }), [completeModel, intervalLabel, lead, showScores, forecastView, showResiduals]);
  const domain = getChartDomain(model.extent);
  const description = `${selectedInputs.length} displayed ${selectedInputs.length === 1 ? "reading" : "readings"} of ${inputs.length} monitored ${inputs.length === 1 ? "input" : "inputs"}: ${selectedInputs.map(input => input.stream.label).join(", ")}. `
    + `${inputs.length > 1 ? "Joint detector result across all inputs; no per-sensor attribution. " : ""}`
    + `${forecasts.length ? `${FORECAST_VIEW_LABELS[forecastView]}; ${showResiduals ? "signed residuals below; " : ""}future times are estimated from recent cadence. ` : ""}Independent value scales, shared time, hover and zoom. Times in ${timeZone}.`;
  const option = useMemo(() => buildMonitoringChartOption({ model, colors, timeZone, accessibleDescription: description,
    viewport: inspection ? { mode: "absolute", ...inspection } : { mode: "live" }, layout: "monitoring" }),
  [model, colors, timeZone, description, inspection]);
  const inspect = useCallback((startMs: number, endMs: number) => {
    if (!domain || !Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return;
    setInspection(current => current && Math.abs(current.startMs - startMs) < 1 && Math.abs(current.endMs - endMs) < 1
      ? current : { startMs, endMs });
  }, [domain, setInspection]);
  const zoom = (factor: number, offset = 0) => {
    if (!domain) return;
    const start = inspection?.startMs ?? domain[0], end = inspection?.endMs ?? domain[1];
    const width = Math.min(domain[1] - domain[0], Math.max(1, (end - start) * factor));
    const next = Math.max(domain[0], Math.min((start + end - width) / 2 + offset * (end - start), domain[1] - width));
    inspect(next, next + width);
  };
  const navigate = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget || !["+", "=", "-", "Home", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Home") setInspection(undefined);
    else if (event.key === "+" || event.key === "=") zoom(0.5);
    else if (event.key === "-") zoom(2);
    else zoom(1, event.key === "ArrowLeft" ? -0.2 : 0.2);
  };
  const loading = history.monitoring.loading || [...history.histories.values()].some(item => item.loading);
  const errors = [...new Set([history.monitoring.error, ...[...history.histories.values()].map(item => item.error)].filter(Boolean))];
  // Both requests keep polling, so a failure clears itself once the service answers again.
  const problem = errors.length ? `${errors.join(" ")} Retrying automatically.` : "";
  const stage = service.operational_status.stage.replace(/_/g, " ");
  const panes = model.readings.length + Number(Boolean(model.detectorInputs?.length) || Boolean(model.forecasts?.some(forecast => !forecast.readingId)))
    + (showResiduals ? model.forecasts?.length ?? 0 : 0) + new Set(model.secondarySeries.map(series => series.pane)).size;
  const latest = completeModel.secondarySeries[0]?.latestObservation;
  const modelName = service.model_type?.replace(/^aberrant_/, "").replace(/_/g, " ");
  return <section className="ex-preview-history mn-history" aria-label="Monitoring history">
    <div className="ex-preview-section-heading"><h3>{forecasts.length ? "Forecast and deviations" : "Inputs and detection"}</h3>
      {model.extent && <div className="ex-history-tools" role="group" aria-label="Chart controls">
        {forecasts.length > 0 && <ForecastViewButton view={forecastView} onChange={setForecastView} />}
        <button aria-label="Zoom in" title="Zoom in" disabled={!domain} onClick={() => zoom(0.5)}><Plus size={15} /></button>
        <button aria-label="Zoom out" title="Zoom out" disabled={!inspection} onClick={() => zoom(2)}><Minus size={15} /></button>
        <button disabled={!inspection} onClick={() => setInspection(undefined)}><RotateCcw size={13} />{inspection ? "Return to live" : "Live"}</button>
      </div>}
    </div>
    <p className="mn-history-scope">{modelName && <strong>{modelName}</strong>}{inputs.length > 1
      ? `Joint result across all ${inputs.length} inputs. Display selection does not change detection.` : "Reading and detector result on one timeline."}</p>
    {inputs.length > 1 && <details className="mn-history-readings"><summary>Displayed readings · {selectedInputs.length} of {inputs.length}</summary>
      <fieldset><legend>Choose up to {MAX_VISIBLE_READINGS} readings to display</legend>{inputs.map(input => {
        const checked = selectedInputs.some(selected => selected.stream.id === input.stream.id);
        return <label key={input.stream.id} title={input.path}><input type="checkbox" checked={checked}
          disabled={checked ? selectedInputs.length === 1 : selectedInputs.length >= MAX_VISIBLE_READINGS}
          onChange={() => setChosen(checked ? selectedInputs.filter(selected => selected.stream.id !== input.stream.id).map(selected => selected.stream.id)
            : [...selectedInputs.map(selected => selected.stream.id), input.stream.id])} />
          <span>{input.stream.label}{input.stream.unit && <small>{input.stream.unit}</small>}</span></label>;
      })}</fieldset>
    </details>}
    {selection.controlCatalog.length > 1 && <TelemetryDetectorControls detectors={selection.controlCatalog}
      selected={selection.selectedDetectorIds} unavailableIds={selection.unavailableIds} onSelect={selection.onSelect} />}
    {forecasts.length > 0 && <ForecastControls forecasts={forecasts} lead={lead} onLead={setChosenLead}
      view={forecastView} showResiduals={showResiduals} onResiduals={setShowResiduals}
      showScores={showScores} onScores={setShowScores} intervalLabel={intervalLabel} timeZone={timeZone} />}
    {forecasts.length > 0 && presentation.error && <p className="mn-history-problem" role="status">{presentation.error} <button onClick={presentation.retry}>Retry</button></p>}
    {model.extent ? <>
      {!latest && <p className="ex-history-monitoring" role="status">{loading ? "Loading history…" : `Monitoring: ${stage} · Awaiting evaluated observations`}</p>}
      <div className="ex-history-navigation" role="group" aria-label="Chart navigation" tabIndex={0} onKeyDown={navigate}
        style={{ height: `${panes * 148 + 60 + (forecasts.length ? model.readings.length * 60 : 0)}px` }}>
        <EChart option={option} resolvedTheme={resolvedTheme} accessibleDescription={description} onViewportChange={inspect}
          className="mn-history-chart" />
      </div>
    </> : <div className={`mn-history-empty${problem && !loading ? " is-error" : ""}`} role="status">
      <strong>{loading ? "Loading recorded inputs…" : problem ? "History could not be loaded" : "Waiting for recorded inputs and detector results"}</strong>
      {!loading && <span>{problem || `Monitoring is ${stage}. The chart appears with the first recorded inputs.`}</span>}
    </div>}
    {latest && <output className="mn-history-result" aria-label="Latest detector result">
      <span>Latest {inputs.length > 1 ? "joint " : ""}result · {formatChartTime(latest.timeMs, timeZone, "tooltip")}</span>
      {(!forecasts.length || showScores) && <strong>{completeModel.secondarySeries[0]!.name}: {latest.value !== null ? formatNumber(latest.value) : latest.isInfinite ? "∞" : "unavailable"}</strong>}
      <span>{(!forecasts.length || showScores) && <>Score threshold: {latest.threshold !== null ? formatNumber(latest.threshold) : "unavailable"} · </>}{latest.alarmActive ? "Service alarm active" : "Service alarm inactive"}</span>
    </output>}
    {model.extent && <p className="mn-history-key">{(!forecasts.length || showScores) && "Dashed red: score threshold · "}Red vertical lines: service alarms. Each reading keeps its own scale.</p>}
    {model.extent && problem && <p className="mn-history-problem" role="status">{problem}</p>}
  </section>;
}
