import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Menu, PanelLeft, Plus, X } from "lucide-react";
import { Link, useBlocker, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { AppHeader } from "@/components/AppHeader";
import { Button } from "@/components/ui/button";
import { apiUtils } from "@/lib/api-client";
import { ExplorerSidebar } from "../explorer/ExplorerSidebar";
import { navigationRows, searchNavigation } from "../explorer/navigationIndex";
import type { ExplorerNode } from "../explorer/navigationIndex";
import { navigationDraft } from "@/lib/navigation-draft";
import { ReadingHistoryCache } from "../explorer/readingHistoryCache";
import { SystemLiveTelemetry } from "./systemLiveTelemetry";
import { SystemLiveControls } from "./SystemLiveControls";
import { useSystemDocument } from "./useSystemDocument";
import { createEmptySystem, serializeSystemDocument } from "./systemDocument";
import { buildSourcesIndex, scopeForNode, scopeReadingIds, safeServiceReturn } from "./collectionRules";
import { useRecordingRules } from "./useRecordingRules";
import { SourceRecordingInspector } from "./SourceRecordingInspector";
import type { SystemDocument, SystemEntityKind, SystemRuntime } from "./systemTypes";
import "../explorer/explorer.css";
import "./sources.css";

const Preview = lazy(() => import("../explorer/ExplorerPreview"));
const Settings = lazy(() => import("../explorer/ExplorerSettings"));
const StructureEditor = lazy(() => import("./SystemStructureEditor").then(module => ({ default: module.SystemStructureEditor })));
const empty = createEmptySystem();

export function SourcesWorkspace() {
  const { userId, isAuthenticated } = useAuth();
  const system = useSystemDocument({ isAuthenticated, accountKey: userId });
  const document = system.document ?? empty;
  const index = useMemo(() => buildSourcesIndex(document), [document]);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const selected = useMemo(() => {
    const reading = params.get("reading"), broker = params.get("broker"), topic = params.get("topic");
    return [...index.nodes.values()].find(node => reading ? node.objectId === reading && node.entityKind === "stream"
      : broker && node.connectionId === broker && (topic !== null ? node.kind === "topic" && node.topic === topic : node.kind === "connection"));
  }, [index, params]);
  const scope = scopeForNode(selected);
  const ids = useMemo(() => selected ? scopeReadingIds(index, selected) : [], [index, selected]);
  const inspected = useMemo(() => selected ? { ...selected, streamIds: ids } : undefined, [selected, ids]);
  const [browseKey, setBrowseKey] = useState(() => {
    try { return localStorage.getItem(`data-sources-navigation:${userId}`) ?? index.rootKey; } catch { return index.rootKey; }
  });
  const currentKey = index.nodes.has(browseKey) ? browseKey : index.rootKey;
  const [query, setQuery] = useState("");
  const [positions] = useState(() => new Map());
  const [mobileOpen, setMobileOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [panel, setPanel] = useState<"settings" | undefined>();
  const [editor, setEditor] = useState<{ kind: SystemEntityKind; id?: string; key: number }>();
  const toggle = useRef<HTMLButtonElement>(null);
  const [telemetry] = useState(() => new SystemLiveTelemetry());
  const history = useMemo(() => navigationDraft(`history:${userId}`, () => new ReadingHistoryCache(userId)), [userId]);
  const rules = useRecordingRules(system.snapshot, scope?.connection_id, system.applyRules);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => rules.dirty &&
    (nextLocation.pathname !== currentLocation.pathname || new URLSearchParams(nextLocation.search).get("broker") !== params.get("broker")));
  const bindings = system.snapshot?.runtime.bindings;
  const numericIds = useMemo(() => new Set(document.streams.filter(item => item.value_type === "number").map(item => item.id)), [document.streams]);
  const liveIds = useMemo(() => ids.filter(id => !numericIds.has(id) || bindings?.[id]?.policy.mode === "off"), [ids, numericIds, bindings]);
  const brokerId = scope?.connection_id;
  const { revision, refreshRuntime, updateRuntime } = system;
  const hasSnapshot = !!system.snapshot;
  const returnTo = params.get("returnTo");
  const safeReturn = safeServiceReturn(returnTo);
  const requestedMissing = system.document && (params.has("broker") || params.has("reading") || params.has("topic")) && !selected;

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => { if (rules.dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [rules.dirty]);
  useEffect(() => {
    telemetry.configure(document, system.revision ?? 0, String(userId ?? ""), system.canEdit);
  }, [telemetry, document, system.revision, userId, system.canEdit]);
  useEffect(() => { telemetry.setScope(liveIds); }, [telemetry, liveIds]);
  useEffect(() => {
    const visibility = () => window.document.hidden ? telemetry.pause() : telemetry.resume();
    window.document.addEventListener("visibilitychange", visibility);
    return () => { window.document.removeEventListener("visibilitychange", visibility); telemetry.stop(); };
  }, [telemetry]);
  useEffect(() => {
    if (!hasSnapshot) return;
    const controller = new AbortController();
    let busy = false;
    const streamIds = brokerId ? document.streams.filter(item => item.connection_id === brokerId).map(item => item.id) : document.streams.map(item => item.id);
    const poll = async () => {
      if (window.document.hidden || busy) return;
      busy = true;
      try {
        const next = await apiUtils.post<{ revision: number; runtime: SystemRuntime }>("/v1/system/collection/status", { stream_ids: streamIds }, { signal: controller.signal, redirectOnUnauthorized: false });
        if (!controller.signal.aborted) { if (next.revision !== revision) void refreshRuntime(); else updateRuntime(next); }
      } catch { /* Keep acknowledged settings through an outage. */ }
      finally { busy = false; }
    };
    const timer = setInterval(() => void poll(), 5000);
    return () => { clearInterval(timer); controller.abort(); };
  }, [document, brokerId, revision, refreshRuntime, updateRuntime, hasSnapshot]);

  const browse = (key: string) => {
    setBrowseKey(key); setQuery("");
    try { localStorage.setItem(`data-sources-navigation:${userId}`, key); } catch { /* Navigation still works without storage. */ }
  };
  const select = (node: ExplorerNode) => {
    const target = scopeForNode(node);
    if (!target) return;
    const next = new URLSearchParams();
    next.set("broker", target.connection_id);
    if (target.kind === "reading") next.set("reading", target.reading_id!);
    if (target.kind === "topic") next.set("topic", target.topic_prefix!);
    if (safeReturn !== "/") next.set("returnTo", safeReturn);
    setParams(next); setMobileOpen(false);
  };
  const openEditor = (kind: SystemEntityKind, id?: string) => { setPanel(undefined); setEditor({ kind, id, key: Date.now() }); };
  const rename = async (kind: SystemEntityKind, id: string, label: string) => { if (!await system.rename(kind, id, label)) throw new Error("The name was not saved."); };
  const exportCatalogue = async () => {
    const saved = await system.refresh();
    if (!saved) return;
    const url = URL.createObjectURL(new Blob([serializeSystemDocument(saved)], { type: "application/json" }));
    const link = window.document.createElement("a"); link.href = url; link.download = "aberration-system.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const importCatalogue = async (next: SystemDocument, revision: number) => {
    if (rules.dirty) return false;
    const saved = await system.save(next, revision);
    if (saved) { browse(index.rootKey); setParams({}); }
    return saved;
  };
  const rows = (query.trim() ? searchNavigation(index, query).map(node => ({ node, label: node.entityKind === "stream"
    ? document.streams.find(stream => stream.id === node.objectId)?.label ?? node.label : node.label })) : navigationRows(index, currentKey))
    .map(row => ({ ...row, detail: row.node.entityKind === "stream" ? document.streams.find(stream => stream.id === row.node.objectId)?.payload_pointer ?? "Reading" : undefined }));
  const sidebar = <ExplorerSidebar index={index} scopeKey={currentKey} title={index.nodes.get(currentKey)?.label ?? "Data sources"}
    catalogueGroups={[]} rows={rows} query={query} selectedKey={selected?.key ?? null} positions={positions} loading={system.status === "loading"}
    onQuery={setQuery} onScope={browse} onOpen={select} onBrowse={node => browse(node.key)}
    onBack={() => query ? setQuery("") : browse(index.nodes.get(currentKey)?.parentKey ?? index.rootKey)}
    onInspect={() => { const node = index.nodes.get(currentKey); if (node) select(node); }}
    onSettings={() => { setMobileOpen(false); setPanel("settings"); }} onWorkspace={() => navigate(safeReturn)} onDismiss={() => setMobileOpen(false)} />;
  const dismiss = () => { if (!system.saving) { setPanel(undefined); setEditor(undefined); } };
  const showOverview = () => setParams(safeReturn === "/" ? {} : { returnTo: safeReturn });
  const sourceEditor = scope && <SourceRecordingInspector key={JSON.stringify(scope)} scope={scope} ids={ids} document={document}
    runtime={system.snapshot?.runtime} canEdit={system.canEdit} draft={rules} />;
  const preview = inspected && <Suspense fallback={<p role="status">Opening source…</p>}><Preview node={inspected} index={index} document={document}
    telemetry={telemetry} historyCache={history} canEdit={system.canEdit && !rules.dirty} saving={system.saving} error={system.error} onRename={rename}
    onEdit={openEditor} onClose={showOverview} runtime={system.snapshot?.runtime} connectionStatusOnly collectionControls={sourceEditor} /></Suspense>;
  const onDirtyLeave = async (save: boolean) => {
    if (save && !await rules.apply()) return;
    if (!save) rules.discard();
    if (blocker.state === "blocked") blocker.proceed();
  };
  return <div className={`ex-shell sources-shell${sidebarOpen ? "" : " ex-sidebar-hidden"}`}>
    {sidebarOpen && <div className="ex-sidebar-dock sources-desktop-sidebar">{sidebar}</div>}
    <main className="ex-main" aria-label="Data sources workspace"><AppHeader leading={<button ref={toggle} className="app-icon-button" aria-label="Toggle data sources explorer"
      onClick={() => window.matchMedia("(max-width: 760px)").matches ? setMobileOpen(true) : setSidebarOpen(value => !value)}>{sidebarOpen ? <PanelLeft size={19} /> : <Menu size={19} />}</button>} />
      <div className="ex-main-content"><div className="ex-workspace-heading"><h1>Data sources</h1><div className="ex-workspace-actions">
        {safeReturn !== "/" && <Link to={safeReturn}>Return to service setup</Link>}
        {selected && liveIds.length > 0 && <SystemLiveControls telemetry={telemetry} canStart={system.canEdit} canView={!!system.snapshot} disabled={system.saving} />}
        {system.canEdit && <Button variant="outline" disabled={rules.dirty} onClick={() => openEditor("connection")}><Plus size={16} />Add broker</Button>}</div></div>
        {system.error && <p role="alert" className="ex-banner ex-error">{system.error}<button onClick={() => void system.refreshRuntime()}>Retry</button></p>}
        {requestedMissing ? <p role="alert">Source not found. <button onClick={showOverview}>Show brokers</button></p> : preview ?? <section aria-label="Broker overview" className="source-overview">
          <p className="ex-muted">Set up brokers and choose which registered readings to record.</p>
          {!document.connections.length && <p>{system.status === "loading" ? "Loading data sources…" : "No brokers configured yet."}</p>}
          {document.connections.map(broker => {
            const readings = document.streams.filter(stream => stream.connection_id === broker.id);
            const enabled = readings.filter(stream => system.snapshot?.runtime.bindings?.[stream.id]?.policy.mode !== "off" && !!system.snapshot?.runtime.bindings?.[stream.id]).length;
            const state = system.snapshot?.runtime.ingress?.sources?.[broker.id]?.state;
            const node = index.nodes.get(index.objectKeys.get(broker.id)![0]!)!;
            return <button key={broker.id} className="source-broker" onClick={() => { select(node); browse(node.key); }}><strong>{broker.label}</strong>
              <span>{readings.length} readings · {enabled} enabled</span><span>{state === "connected" ? "Connected" : state ?? "Not subscribed"}</span></button>;
          })}
        </section>}
      </div></main>
    <Dialog.Root open={mobileOpen} onOpenChange={setMobileOpen}><Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" /><Dialog.Content className="ex-mobile-sidebar"
      onCloseAutoFocus={event => { event.preventDefault(); toggle.current?.focus(); }}><Dialog.Title className="ex-sr-only">Data sources explorer</Dialog.Title><Dialog.Description className="ex-sr-only">Browse brokers, topic folders and readings.</Dialog.Description>{sidebar}</Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={!!panel || !!editor} onOpenChange={open => { if (!open) dismiss(); }}><Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" /><Dialog.Content className="ex-dialog">
      <header><Dialog.Title>{editor ? "Edit data source" : "Catalogue settings"}</Dialog.Title><button aria-label="Close settings" onClick={dismiss}><X size={18} /></button></header><Dialog.Description className="ex-sr-only">Manage the saved catalogue.</Dialog.Description>
      <Suspense fallback={<p>Loading…</p>}>{editor ? <StructureEditor key={editor.key} document={document} revision={system.revision ?? 0} kind={editor.kind} entityId={editor.id}
        canEdit={system.canEdit} saving={system.saving} saveError={system.error} onSave={system.save} onDone={dismiss} /> : <Settings document={document} revision={system.revision ?? 0}
        canEdit={system.canEdit && !rules.dirty} saving={system.saving} error={system.error} onImport={importCatalogue} onExport={exportCatalogue} onCreate={openEditor} />}</Suspense>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={blocker.state === "blocked"} onOpenChange={open => { if (!open && blocker.state === "blocked") blocker.reset(); }}><Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" /><Dialog.Content className="ex-dialog">
      <Dialog.Title>Unsaved recording changes</Dialog.Title><Dialog.Description>Save this broker’s changes or discard them before leaving.</Dialog.Description>
      <div className="ex-collection-actions"><Button disabled={!rules.preview || !!rules.preview.affected_monitors.length || rules.saving} onClick={() => void onDirtyLeave(true)}>Save and leave</Button>
        <Button variant="outline" onClick={() => void onDirtyLeave(false)}>Discard and leave</Button><Button variant="ghost" onClick={() => { if (blocker.state === "blocked") blocker.reset(); }}>Stay</Button></div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
