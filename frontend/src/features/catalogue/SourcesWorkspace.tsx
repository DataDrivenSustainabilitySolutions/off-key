import { lazy, Suspense, useMemo, useState } from "react";
import { ArrowLeft, Circle, Plug, Plus, RotateCw, Square } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { SystemLiveControls } from "./SystemLiveControls";
import { scopeForNode, safeServiceReturn, policyLabel, recordingScopeReadingIds } from "@/domain/system/collectionRules";
import { useRecording } from "./useRecording";
import { SourceRecordingInspector } from "./SourceRecordingInspector";
import { startRecording, stopRecording } from "./recordingEdits";
import { BrokerCheckMark } from "./BrokerCheck";
import { checkProblem, useBrokerChecks } from "./useBrokerChecks";
import { useCatalogue } from "../workspace/catalogue-context";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { systemApi } from "@/domain/system/systemApi";
import type { SystemDocument, SystemRuntime } from "@/types/system";
import "./sources.css";

const Preview = lazy(() => import("../readings/ExplorerPreview"));

type Tone = "positive" | "warning" | "danger" | "neutral";
/** What a broker row says about recording; a live preview never counts as recording. */
function brokerStatus(source: { state: string; message?: string | null } | undefined, enabled: number,
  check?: string): { label: string; tone: Tone; reason?: string } {
  if (source?.state === "connected") return { label: "Recording", tone: "positive" };
  if (source?.state === "error" || source?.state === "blocked") return { label: "Unavailable", tone: "danger", reason: source.message ?? undefined };
  if (source?.state === "reconnecting") return { label: "Reconnecting…", tone: "warning" };
  if (source || enabled > 0) return { label: "Starting…", tone: "warning" };
  return check ? { label: "Not recorded · Unreachable", tone: "danger", reason: check } : { label: "Not recorded", tone: "neutral" };
}
/** A recorded broker that is retrying or gave up can be retried now. */
const canRetry = (state?: string) => state === "error" || state === "reconnecting";

const enabledReadings = (document: SystemDocument, runtime: SystemRuntime | undefined, id: string) =>
  document.streams.filter(stream => stream.connection_id === id && (runtime?.bindings?.[stream.id]?.policy.mode ?? "off") !== "off").length;

export function SourcesWorkspace() {
  const [params] = useSearchParams();
  const { system, document, index, selected, selectionMissing, streamIds, liveStreamIds, telemetry, history,
    openEditor, selectSource, browse } = useCatalogue();
  const runtime = system.snapshot?.runtime;
  const scope = useMemo(() => scopeForNode(selected), [selected]);
  // MQTT topic policies apply across the whole broker, even when reached through an entity.
  const ids = useMemo(() => scope && selected ? recordingScopeReadingIds(document, selected) : streamIds ?? [], [document, scope, selected, streamIds]);
  const recording = useRecording(system.snapshot, system.applyRules);
  const brokerChecks = useBrokerChecks();
  const sources = runtime?.ingress?.sources;
  // A recorded broker already reports its state; only the others need a check.
  const idleBrokers = document.connections.filter(item => [undefined, "error"].includes(sources?.[item.id]?.state)).map(item => item.id);
  const selectedBroker = selected?.kind === "connection" ? selected.connectionId : undefined;
  const selectedState = selectedBroker ? sources?.[selectedBroker]?.state : undefined;
  const [reconnects, setReconnects] = useState<Record<string, { pending: boolean; error?: string }>>({});
  const retryBroker = async (id: string) => {
    setReconnects(current => ({ ...current, [id]: { pending: true } }));
    try {
      await systemApi.reconnectConnection(id);
      await system.refreshRuntime();
      setReconnects(current => ({ ...current, [id]: { pending: false } }));
    } catch (error) {
      setReconnects(current => ({ ...current, [id]: { pending: false,
        error: error instanceof Error && error.message ? error.message : "The broker could not be reconnected." } }));
    }
  };
  /** Each broker row offers what fits its state: Record, Stop, or Reconnect and Stop. */
  const rowActions = (id: string, label: string) => {
    if (!system.canEdit) return null;
    const state = sources?.[id]?.state;
    const busy = recording.saving === id;
    const recorded = !!state || enabledReadings(document, runtime, id) > 0;
    const stop = <Button variant={canRetry(state) ? "ghost" : "outline"} size="sm" disabled={busy}
      title="Stop recording this broker. Stored history is kept." aria-label={`Stop recording ${label}`}
      onClick={() => void recording.save(stopRecording(id, runtime))}><Square size={12} />{busy ? "Stopping…" : "Stop"}</Button>;
    if (canRetry(state)) {
      const pending = !!reconnects[id]?.pending;
      return <><Button variant="outline" size="sm" disabled={pending} title="Retry the recording connection to this broker now"
        aria-label={`Reconnect ${label}`} onClick={() => void retryBroker(id)}>
        <RotateCw size={14} />{pending ? "Reconnecting…" : "Reconnect"}</Button>{stop}</>;
    }
    if (recorded) return stop;
    return <Button variant="outline" size="sm" disabled={busy} title="Record every message from this broker, also while you are signed out"
      aria-label={`Record ${label}`} onClick={() => void recording.save(startRecording(id))}>
      <Circle size={12} />{busy ? "Starting…" : "Record"}</Button>;
  };
  const safeReturn = safeServiceReturn(params.get("returnTo"));
  useDocumentTitle(selected?.label, "Sources");

  const rename = async (kind: Parameters<typeof system.rename>[0], id: string, label: string) => {
    if (!await system.rename(kind, id, label)) throw new Error("The name was not saved.");
  };
  const readingLinks = <section className="workspace-entity-readings" aria-label="Entity readings">
    <h3>Readings</h3><p className="ex-muted">Select a reading to change how it is recorded.</p>
    {ids.length ? ids.flatMap(id => {
      const stream = document.streams.find(item => item.id === id);
      const node = index.nodes.get(index.objectKeys.get(id)?.[0] ?? "");
      return stream && node ? <button key={id} className="source-broker" onClick={() => selectSource(node)}>
        <strong>{stream.label}</strong><span>{stream.topic}</span><span>{policyLabel(runtime?.bindings?.[id]?.policy)}</span>
      </button> : [];
    }) : <p className="ex-muted">No readings registered for this entity.</p>}
  </section>;
  const configuration = scope ? <>
    {scope.kind === "topic" && <p className="ex-muted">A topic setting applies to all matching readings on this broker.</p>}
    <SourceRecordingInspector key={JSON.stringify(scope)} scope={scope} ids={ids} document={document}
      runtime={runtime} canEdit={system.canEdit} recording={recording} />
  </> : readingLinks;
  const overviewPending = !selected && recording.pending;
  const reconnectError = selectedBroker ? reconnects[selectedBroker]?.error : undefined;
  return <main className="ex-main-content" aria-label="Sources workspace">
    {/* A selected source's preview carries the page title; the heading row keeps only the way back. */}
    <div className="ex-workspace-heading">{selected || selectionMissing
      ? <button type="button" className="source-back" onClick={() => selectSource(null)}><ArrowLeft size={14} aria-hidden="true" />Sources</button>
      : <h1>Sources</h1>}<div className="ex-workspace-actions">
      {safeReturn !== "/" && <Link to={safeReturn}>Return to service setup</Link>}
      {selectedBroker && system.canEdit && canRetry(selectedState) && <Button variant="outline" size="sm"
        disabled={!!reconnects[selectedBroker]?.pending} title="Retry the recording connection to this broker now"
        onClick={() => void retryBroker(selectedBroker)}><RotateCw size={14} />{reconnects[selectedBroker]?.pending ? "Reconnecting…" : "Reconnect"}</Button>}
      {selected && liveStreamIds.length > 0 && <SystemLiveControls telemetry={telemetry} canStart={system.canEdit} canView={!!system.snapshot}
        disabled={system.saving} preview />}
      {system.canEdit && !selected && idleBrokers.length > 0 && <Button variant="outline" disabled={brokerChecks.running}
        title="Connect once to each broker that is not recorded, then disconnect" onClick={() => void brokerChecks.checkAll(idleBrokers)}>
        <Plug size={16} />{brokerChecks.running ? "Checking…" : "Check connections"}</Button>}
      {system.canEdit && <Button variant="outline" onClick={() => openEditor("connection")}><Plus size={16} />Add broker</Button>}
    </div></div>
    {reconnectError && <p role="alert" className="ex-banner ex-error">{reconnectError}</p>}
    {system.error && <p role="alert" className="ex-banner ex-error">{system.error}<button onClick={() => void system.refreshRuntime()}>Retry</button></p>}
    {!selected && recording.problem && <p role="alert" className="ex-banner ex-error">{recording.problem}</p>}
    {overviewPending && <div className="source-confirm" role="alert">
      <p>This stops {recording.pending!.monitors.length === 1 ? "1 running monitor" : `${recording.pending!.monitors.length} running monitors`} that
        {recording.pending!.monitors.length === 1 ? " uses" : " use"} these readings. Their settings are kept.</p>
      <div className="ex-collection-actions"><Button size="sm" onClick={recording.confirm}>Stop monitors and save</Button>
        <Button size="sm" variant="ghost" onClick={recording.cancel}>Cancel</Button></div>
    </div>}
    {selectionMissing ? <p role="alert">Source not found.</p> : selected ? <Suspense fallback={<p role="status">Opening source…</p>}>
      <Preview node={{ ...selected, streamIds: ids }} index={index} document={document} telemetry={telemetry} historyCache={history}
        canEdit={system.canEdit} saving={system.saving} error={system.error} onRename={rename} onEdit={openEditor}
        runtime={runtime} connectionStatusOnly pageTitle collectionControls={configuration}
        connectionCheck={selectedBroker && !selectedState ? checkProblem(brokerChecks.checks[selectedBroker]) : undefined} />
    </Suspense> : <section aria-label="Broker overview" className="source-overview">
      <p className="ex-muted">Record a broker to keep its readings, also while you are signed out.</p>
      {!document.connections.length && <p>{system.status === "loading" ? "Loading sources…" : "No brokers configured yet."}</p>}
      {document.connections.map(item => {
        const readings = document.streams.filter(stream => stream.connection_id === item.id).length;
        const enabled = enabledReadings(document, runtime, item.id);
        const source = sources?.[item.id];
        const check = brokerChecks.checks[item.id];
        const status = brokerStatus(source, enabled, source ? undefined : checkProblem(check));
        const reason = status.reason ?? reconnects[item.id]?.error;
        const node = index.nodes.get(index.objectKeys.get(item.id)![0]!)!;
        return <div key={item.id} className={`source-broker source-broker--${status.tone}`}>
          <button type="button" className="source-broker-open" onClick={() => { selectSource(node); browse(node.key); }}>
            <strong>{item.label}{check && <BrokerCheckMark check={check} />}</strong></button>
          <span>{readings} readings{enabled ? ` · ${enabled === readings ? "all" : enabled} recorded` : ""}</span>
          {reason && <span className="source-broker-reason">{reason}</span>}
          <div className="source-broker-status"><span className={`mn-state mn-state--${status.tone}`}>{status.label}</span>
            {rowActions(item.id, item.label)}</div>
        </div>;
      })}
    </section>}
  </main>;
}
