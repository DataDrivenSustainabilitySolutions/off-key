import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { ArrowLeft, Plug, Plus, RotateCw } from "lucide-react";
import { Link, useBlocker, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { SystemLiveControls } from "./SystemLiveControls";
import { scopeForNode, safeServiceReturn, policyLabel, recordingScopeReadingIds } from "@/domain/system/collectionRules";
import { useRecordingRules } from "./useRecordingRules";
import { SourceRecordingInspector } from "./SourceRecordingInspector";
import { BrokerCheckMark } from "./BrokerCheck";
import { useBrokerChecks } from "./useBrokerChecks";
import { useCatalogue } from "../workspace/catalogue-context";
import { catalogueSelection } from "../workspace/catalogue-navigation";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { systemApi } from "@/domain/system/systemApi";
import "./sources.css";

const Preview = lazy(() => import("../readings/ExplorerPreview"));

/** Broker connection states share the dot-and-label indicator used by services. */
const brokerTone = (state?: string) => state === "connected" ? "positive"
  : state === "error" || state === "blocked" ? "danger" : state ? "warning" : "neutral";
const brokerLabel = (state?: string) => state === "connected" ? "Connected"
  : state === "error" || state === "blocked" ? "Unavailable"
    : state ? `${state[0]!.toUpperCase()}${state.slice(1)}` : "Not subscribed";

export function SourcesWorkspace() {
  const [params] = useSearchParams();
  const { system, document, index, selected, selectionMissing, streamIds, liveStreamIds, telemetry, history,
    openEditor, selectSource, browse, setEditingLocked } = useCatalogue();
  const scope = useMemo(() => scopeForNode(selected), [selected]);
  // MQTT topic policies apply across the whole broker, even when reached through an entity.
  const ids = useMemo(() => scope && selected ? recordingScopeReadingIds(document, selected) : streamIds ?? [], [document, scope, selected, streamIds]);
  const rules = useRecordingRules(system.snapshot, selected?.connectionId, system.applyRules);
  const brokerChecks = useBrokerChecks();
  const sources = system.snapshot?.runtime.ingress?.sources;
  // A broker in use already reports its live state; only idle or failed ones need a check.
  const idleBrokers = document.connections.filter(broker => [undefined, "error"].includes(sources?.[broker.id]?.state)).map(broker => broker.id);
  // A recorded broker that is retrying or gave up can be retried now.
  const selectedSource = selected?.kind === "connection" ? sources?.[selected.connectionId ?? ""] : undefined;
  const canReconnect = system.canEdit && !!selectedSource && ["error", "reconnecting"].includes(selectedSource.state);
  const [reconnect, setReconnect] = useState<{ id?: string; pending: boolean; error?: string }>({ pending: false });
  const reconnectError = reconnect.id === selected?.connectionId ? reconnect.error : undefined;
  const retryBroker = async (id: string) => {
    setReconnect({ id, pending: true });
    try {
      await systemApi.reconnectConnection(id);
      await system.refreshRuntime();
      setReconnect({ id, pending: false });
    } catch (error) {
      setReconnect({ id, pending: false, error: error instanceof Error && error.message ? error.message : "The broker could not be reconnected." });
    }
  };
  useUnsavedChanges(rules.dirty);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => {
    if (!rules.dirty) return false;
    if (nextLocation.pathname !== currentLocation.pathname) return true;
    const next = catalogueSelection(index, new URLSearchParams(nextLocation.search));
    return next?.connectionId !== selected?.connectionId || !scopeForNode(next);
  });
  const safeReturn = safeServiceReturn(params.get("returnTo"));
  useDocumentTitle(selected?.label, "Sources");
  useEffect(() => {
    setEditingLocked(rules.dirty);
    return () => setEditingLocked(false);
  }, [rules.dirty, setEditingLocked]);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => { if (rules.dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [rules.dirty]);

  const rename = async (kind: Parameters<typeof system.rename>[0], id: string, label: string) => {
    if (!await system.rename(kind, id, label)) throw new Error("The name was not saved.");
  };
  const onDirtyLeave = async (save: boolean) => {
    if (save && !await rules.apply()) return;
    if (!save) rules.discard();
    if (blocker.state === "blocked") blocker.proceed();
  };
  const readingLinks = <section className="workspace-entity-readings" aria-label="Entity readings">
    <h3>Readings</h3><p className="ex-muted">Select a reading to configure its recording policy.</p>
    {ids.length ? ids.flatMap(id => {
      const stream = document.streams.find(item => item.id === id);
      const node = index.nodes.get(index.objectKeys.get(id)?.[0] ?? "");
      return stream && node ? <button key={id} className="source-broker" onClick={() => selectSource(node)}>
        <strong>{stream.label}</strong><span>{stream.topic}</span><span>{policyLabel(system.snapshot?.runtime.bindings?.[id]?.policy)}</span>
      </button> : [];
    }) : <p className="ex-muted">No readings registered for this entity.</p>}
  </section>;
  const configuration = scope ? <>
    {scope.kind === "topic" && <p className="ex-muted">Topic recording policies apply to all matching readings on this broker.</p>}
    <SourceRecordingInspector key={JSON.stringify(scope)} scope={scope} ids={ids} document={document}
      runtime={system.snapshot?.runtime} canEdit={system.canEdit} draft={rules} />
  </> : readingLinks;
  return <>
    <main className="ex-main-content" aria-label="Sources workspace">
      {/* A selected source's preview carries the page title; the heading row keeps only the way back. */}
      <div className="ex-workspace-heading">{selected || selectionMissing
        ? <button type="button" className="source-back" onClick={() => selectSource(null)}><ArrowLeft size={14} aria-hidden="true" />Sources</button>
        : <h1>Sources</h1>}<div className="ex-workspace-actions">
        {safeReturn !== "/" && <Link to={safeReturn}>Return to service setup</Link>}
        {canReconnect && <Button variant="outline" disabled={reconnect.pending} title="Retry the recording connection to this broker now"
          onClick={() => void retryBroker(selected!.connectionId!)}><RotateCw size={16} />{reconnect.pending ? "Reconnecting…" : "Reconnect"}</Button>}
        {selected && liveStreamIds.length > 0 && <SystemLiveControls telemetry={telemetry} canStart={system.canEdit} canView={!!system.snapshot} disabled={system.saving} />}
        {system.canEdit && !selected && idleBrokers.length > 0 && <Button variant="outline" disabled={brokerChecks.running}
          title="Connect once to each broker that is not in use, then disconnect" onClick={() => void brokerChecks.checkAll(idleBrokers)}>
          <Plug size={16} />{brokerChecks.running ? "Checking…" : "Check connections"}</Button>}
        {system.canEdit && <Button variant="outline" disabled={rules.dirty} onClick={() => openEditor("connection")}><Plus size={16} />Add broker</Button>}
      </div></div>
      {reconnectError && <p role="alert" className="ex-banner ex-error">{reconnectError}</p>}
      {system.error && <p role="alert" className="ex-banner ex-error">{system.error}<button onClick={() => void system.refreshRuntime()}>Retry</button></p>}
      {selectionMissing ? <p role="alert">Source not found.</p> : selected ? <Suspense fallback={<p role="status">Opening source…</p>}>
        <Preview node={{ ...selected, streamIds: ids }} index={index} document={document} telemetry={telemetry} historyCache={history}
          canEdit={system.canEdit && !rules.dirty} saving={system.saving} error={system.error} onRename={rename} onEdit={openEditor}
          runtime={system.snapshot?.runtime} connectionStatusOnly pageTitle collectionControls={configuration} />
      </Suspense> : <section aria-label="Broker overview" className="source-overview">
        <p className="ex-muted">Set up brokers and choose which registered readings to record.</p>
        {!document.connections.length && <p>{system.status === "loading" ? "Loading sources…" : "No brokers configured yet."}</p>}
        {document.connections.map(broker => {
          const readings = document.streams.filter(stream => stream.connection_id === broker.id);
          const enabled = readings.filter(stream => system.snapshot?.runtime.bindings?.[stream.id]?.policy.mode !== "off" && !!system.snapshot?.runtime.bindings?.[stream.id]).length;
          const state = system.snapshot?.runtime.ingress?.sources?.[broker.id]?.state;
          const node = index.nodes.get(index.objectKeys.get(broker.id)![0]!)!;
          return <button key={broker.id} className={`source-broker source-broker--${brokerTone(state)}`} onClick={() => { selectSource(node); browse(node.key); }}><strong>{broker.label}{brokerChecks.checks[broker.id] && <BrokerCheckMark check={brokerChecks.checks[broker.id]!} />}</strong>
            <span>{readings.length} readings · {enabled} enabled</span><span className={`mn-state mn-state--${brokerTone(state)}`}>{brokerLabel(state)}</span></button>;
        })}
      </section>}
    </main>
    <Dialog.Root open={blocker.state === "blocked"} onOpenChange={open => { if (!open && !rules.saving && blocker.state === "blocked") blocker.reset(); }}>
      <Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" /><Dialog.Content className="ex-dialog"
        onEscapeKeyDown={event => { if (rules.saving) event.preventDefault(); }}>
        <Dialog.Title>Unsaved recording changes</Dialog.Title>
        <Dialog.Description>Save this broker’s changes or discard them before leaving.</Dialog.Description>
        <div className="ex-collection-actions">
          <Button disabled={!rules.preview || !!rules.preview.affected_monitors.length || rules.saving} onClick={() => void onDirtyLeave(true)}>Save and leave</Button>
          <Button variant="outline" disabled={rules.saving} onClick={() => void onDirtyLeave(false)}>Discard and leave</Button>
          <Button variant="ghost" disabled={rules.saving} onClick={() => { if (blocker.state === "blocked") blocker.reset(); }}>Stay</Button>
        </div>
      </Dialog.Content></Dialog.Portal>
    </Dialog.Root>
  </>;
}
