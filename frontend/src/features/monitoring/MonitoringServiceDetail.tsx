import { lazy, Suspense, useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useSearchParams } from "react-router-dom";
import { ArrowLeft, Star, X } from "lucide-react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { getErrorMessage } from "@/lib/errors";
import type { ActiveService, JsonValue } from "@/types/monitoring";
import { InlineName } from "../catalogue/InlineName";
import { ExplorerHistoryChart } from "../explorer/ExplorerHistoryChart";
import type { ReadingHistoryCache } from "../explorer/readingHistoryCache";
import type { SystemDocument } from "../catalogue/systemTypes";
import { formatServiceTime, serviceName, serviceState, strategyName, type MonitoringInput } from "./serviceModel";
import type { PipelineState } from "../pipelines/PipelineDiagnostics";

const PipelineRun = lazy(() => import("../pipelines/PipelineRunView"));

type Configuration = { monitoring: Record<string, JsonValue>; performance_config: Record<string, JsonValue> };
type Props = { service: ActiveService; inputs: MonitoringInput[]; document: SystemDocument; historyCache?: ReadingHistoryCache; canEdit: boolean; favourite: boolean;
  pipelineState?: PipelineState;
  onFavourite: () => void; onRename: (name: string) => Promise<void>; onBack: () => void; onDeleted: () => Promise<void> };
const tabs = [{ id: "overview", label: "Overview" }, { id: "evidence", label: "Evidence" }, { id: "pipeline", label: "Pipeline" }, { id: "configuration", label: "Configuration" }];

export default function MonitoringServiceDetail({ service, inputs, document, historyCache, canEdit, favourite, pipelineState, onFavourite, onRename, onBack, onDeleted }: Props) {
  const [params, setParams] = useSearchParams();
  const tab = tabs.some(item => item.id === params.get("tab")) ? params.get("tab")! : "overview";
  const [configuration, setConfiguration] = useState<Configuration>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const state = serviceState(service);
  const name = serviceName(service, inputs);
  const progress = service.operational_status.progress;
  const coverage = service.operational_status.coverage;
  const activity = service.operational_status.activity;
  const inputNames = new Map(inputs.map(input => [input.binding.telemetry_key, input.stream.label]));
  const describeInputs = (sensors: string[]) => sensors.map(sensor => inputNames.get(sensor) ?? sensor).join(", ");
  const selectedInput = inputs.find(input => input.stream.id === params.get("stream")) ?? inputs[0];
  useEffect(() => {
    const controller = new AbortController();
    void apiUtils.get<{ configuration?: Configuration }>(`${API_CONFIG.ENDPOINTS.MONITORING.DETAILS}?container_name=${encodeURIComponent(service.container_name)}`,
      { signal: controller.signal, redirectOnUnauthorized: false }).then(result => {
      if (!controller.signal.aborted) { setConfiguration(result.configuration); setError(""); }
    }, reason => { if (!controller.signal.aborted) setError(getErrorMessage(reason)); });
    return () => controller.abort();
  }, [service.id, service.container_name, retry]);
  const chooseTab = (next: string, streamId?: string) => {
    const search = new URLSearchParams(params); search.set("tab", next);
    if (streamId) search.set("stream", streamId); else if (next !== "evidence") search.delete("stream");
    setParams(search);
  };
  const remove = async () => {
    setDeleting(true); setDeleteError("");
    try {
      await apiUtils.delete(API_CONFIG.ENDPOINTS.MONITORING.DELETE(service.id), undefined, { timeout: API_CONFIG.MONITORING_LIFECYCLE_TIMEOUT });
      setConfirm(false); await onDeleted();
    } catch (reason) { setDeleteError(getErrorMessage(reason)); }
    finally { setDeleting(false); }
  };
  return <section className="mn-detail" aria-label="Monitoring service details">
    <button className="mn-back" onClick={onBack}><ArrowLeft size={14} />Monitoring</button>
    <div className="mn-detail-header"><div><h2><InlineName value={name} editable={canEdit} onSave={onRename} ariaLabel="Rename service" /></h2>
      <small>{strategyName(service)}{service.model_type ? ` · ${service.model_type.replace(/^aberrant_/, "").replace(/_/g, " ")}` : ""}</small></div>
      <div className="mn-detail-actions"><button className="mn-favourite ex-icon-button" aria-pressed={favourite} aria-label={favourite ? "Remove service from favourites" : "Add service to favourites"} onClick={onFavourite}><Star size={17} /></button>
        <button className="ex-icon-button" aria-label="Close service" onClick={onBack}><X size={17} /></button></div></div>
    <dl className="mn-summary"><div><dt>State</dt><dd><span className={`mn-state mn-state--${state.tone}`}>{state.label}</span></dd></div>
      <div><dt>Inputs</dt><dd>{service.mqtt_topics.length} {service.mqtt_topics.length === 1 ? "reading" : "readings"}</dd></div>
      <div><dt>Processed</dt><dd>{service.operational_status.processed_message_count.toLocaleString()}</dd></div>
      <div><dt>Last update</dt><dd><time dateTime={service.operational_status.updated_at ?? undefined}>{formatServiceTime(service.operational_status.updated_at)}</time></dd></div></dl>
    <div className="mn-tabs" role="tablist" aria-label="Service details">{tabs.map((item, index) => <button key={item.id} id={`monitor-tab-${item.id}`} role="tab"
      aria-selected={tab === item.id} aria-controls={`monitor-panel-${item.id}`} tabIndex={tab === item.id ? 0 : -1} onClick={() => chooseTab(item.id)} onKeyDown={event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
        chooseTab(tabs[next]!.id); window.document.getElementById(`monitor-tab-${tabs[next]!.id}`)?.focus();
      }}>{item.label}</button>)}</div>
    <div className="mn-detail-panel" role="tabpanel" id={`monitor-panel-${tab}`} aria-labelledby={`monitor-tab-${tab}`}>
      {tab === "pipeline" && <Suspense fallback={<p role="status">Opening pipeline…</p>}><PipelineRun serviceId={service.id} displayName={service.display_name ?? service.container_name} canEdit={canEdit} state={pipelineState} /></Suspense>}
      {tab === "overview" && <>
        {progress && <section><h3>{state.label}</h3><p className="ex-muted">{progress.current.toLocaleString()} / {progress.target.toLocaleString()} samples</p>
          <div className="mn-progress" role="progressbar" aria-label="Monitoring preparation" aria-valuemin={0} aria-valuemax={progress.target} aria-valuenow={Math.min(progress.current, progress.target)}>
            <div style={{ width: `${Math.min(100, Math.max(0, progress.current / Math.max(1, progress.target) * 100))}%` }} /></div></section>}
        {service.operational_status.error && <p className="ex-preview-error" role="alert">{service.operational_status.error}</p>}
        {service.operational_status.detail && <p className="ex-muted">{service.operational_status.detail}</p>}
        {activity && <section className="mn-section"><h3>Monitoring activity</h3>
          <dl className="mn-configuration"><div><dt>Last valid input</dt><dd>{formatServiceTime(activity.last_input_at)}</dd></div>
            <div><dt>Last inference</dt><dd>{formatServiceTime(activity.last_inference_at)}</dd></div>
            <div><dt>Last evidence saved</dt><dd>{formatServiceTime(activity.last_persisted_at)}</dd></div></dl>
          {activity.missing_sensors.length > 0 && <p className="ex-muted">Missing inputs: {describeInputs(activity.missing_sensors)}</p>}
          {activity.stale_sensors.length > 0 && <p className="ex-muted">Stale inputs: {describeInputs(activity.stale_sensors)}</p>}
          <p className="ex-muted">Input freshness budget: {activity.freshness_seconds} seconds.</p>
        </section>}
        <section className="mn-section"><h3>Coverage</h3>
          <p className="ex-muted">Delivery is best effort. Missing observations cannot be replayed.</p>
          {coverage ? <>
            <dl className="mn-configuration"><div><dt>Received observations</dt><dd>{coverage.received_message_count.toLocaleString()}</dd></div>
              <div><dt>Dropped observations</dt><dd>{coverage.dropped_message_count.toLocaleString()}</dd></div>
              <div><dt>Possible interruptions</dt><dd>{coverage.possible_gap_count.toLocaleString()}</dd></div></dl>
            {coverage.has_gaps && <p className="ex-preview-error" role="alert">Monitoring coverage has gaps.
              {coverage.last_gap_at && <> Last gap: {formatServiceTime(coverage.last_gap_at)}.</>}</p>}
            {Object.keys(coverage.dropped_by_reason).length > 0 && <ul>{Object.entries(coverage.dropped_by_reason).map(([reason, count]) =>
              <li key={reason}>{reason.replace(/_/g, " ")}: {count.toLocaleString()}</li>)}</ul>}
          </> : <p className="ex-muted">Coverage has not been reported by this workload.</p>}
        </section>
        <section className={progress ? "mn-section" : undefined}><h3>Monitored readings</h3><ul className="mn-input-list">
          {inputs.map(input => <li key={input.stream.id}><span>{input.stream.label}<small>{input.path}{input.stream.unit ? ` · ${input.stream.unit}` : ""}</small></span>
            <button onClick={() => chooseTab("evidence", input.stream.id)}>Inspect</button></li>)}
          {!inputs.length && service.mqtt_topics.map(topic => <li key={topic}><span>{topic}</span></li>)}
        </ul></section>
      </>}
      {tab === "evidence" && (selectedInput ? <><label className="ex-sr-only" htmlFor="service-reading">Reading</label>
        <select id="service-reading" className="mn-chart-picker" value={selectedInput.stream.id} onChange={event => chooseTab("evidence", event.target.value)}>
          {inputs.map(input => <option key={input.stream.id} value={input.stream.id}>{input.path} / {input.stream.label}</option>)}</select>
        <ExplorerHistoryChart key={`${service.id}:${selectedInput.stream.id}`} stream={selectedInput.stream} binding={selectedInput.binding}
          connection={document.connections.find(connection => connection.id === selectedInput.stream.connection_id)} serviceId={service.id} historyCache={historyCache} />
      </> : <p className="ex-muted">These service inputs are not available in the current catalogue.</p>)}
      {tab === "configuration" && <>
        {error && <p className="ex-preview-error" role="alert">{error}<button onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
        <dl className="mn-configuration"><div><dt>Strategy</dt><dd>{strategyName(service)}</dd></div><div><dt>Model</dt><dd>{service.model_type ?? "Not recorded"}</dd></div>
          {configuration?.monitoring.training_window_size !== undefined && <div><dt>Training samples</dt><dd>{String(configuration.monitoring.training_window_size)}</dd></div>}
          {configuration?.monitoring.calibration_window_size !== undefined && <div><dt>Calibration samples</dt><dd>{String(configuration.monitoring.calibration_window_size)}</dd></div>}
          <div><dt>Notifications</dt><dd>Operator managed</dd></div>
        </dl><p className="ex-muted">Email recipients are configured by the deployment.</p>
        {configuration && Object.keys(configuration.monitoring).length > 0 && <details className="mn-section"><summary>Detector configuration</summary><pre className="mn-json">{JSON.stringify(configuration, null, 2)}</pre></details>}
        <section className="mn-section"><h3>Service</h3><dl className="mn-configuration"><div><dt>Created</dt><dd>{service.created_at ? new Date(service.created_at).toLocaleString() : "Not recorded"}</dd></div>
          <div><dt>Service ID</dt><dd>{service.id}</dd></div></dl>
          {canEdit && <div className="mn-section"><button className="mn-danger" onClick={() => { setDeleteError(""); setConfirm(true); }}>{service.status ? "Stop and remove service" : "Remove service"}</button></div>}</section>
      </>}
    </div>
    <Dialog.Root open={confirm} onOpenChange={next => { if (!deleting) setConfirm(next); }}><Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" />
      <Dialog.Content className="ex-dialog" onEscapeKeyDown={event => { if (deleting) event.preventDefault(); }}>
        <header><Dialog.Title>{service.status ? "Stop and remove service?" : "Remove service?"}</Dialog.Title></header>
        <Dialog.Description>{name}. Collected history is retained.</Dialog.Description>
        {deleteError && <p className="ex-preview-error" role="alert">{deleteError}</p>}
        <div className="mn-section"><button className="mn-danger" disabled={deleting} onClick={() => void remove()}>{deleting ? "Removing…" : "Remove service"}</button>
          <Dialog.Close disabled={deleting}>Cancel</Dialog.Close></div>
      </Dialog.Content></Dialog.Portal></Dialog.Root>
  </section>;
}
