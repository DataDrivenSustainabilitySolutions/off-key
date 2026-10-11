import { lazy, Suspense, useDeferredValue, useEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { ArrowUpRight, Menu, PanelLeft, Plus, X } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { AppHeader } from "@/components/AppHeader";
import { createEmptySystem, serializeSystemDocument } from "../spatial/systemDocument";
import { useSystemDocument } from "../spatial/useSystemDocument";
import { SystemLiveTelemetry } from "../spatial/systemLiveTelemetry";
import { SystemLiveControls } from "../spatial/SystemLiveControls";
import type { SystemDocument, SystemEntityKind } from "../spatial/systemTypes";
import { buildNavigationIndex, navigationRows, navigationTrail, searchNavigation, type ExplorerNode } from "./navigationIndex";
import { loadExplorerPreferences, saveExplorerPreferences, toggleExplorerFavourite } from "./preferences";
import { MonitoringServiceList } from "../monitoring/MonitoringServiceList";
import { buildMonitoringIndex, serviceName, servicesForScope } from "../monitoring/serviceModel";
import { useMonitoringServices } from "../monitoring/useMonitoringServices";
import { ExplorerSidebar } from "./ExplorerSidebar";
import { ExplorerSidebarResize } from "./ExplorerSidebarResize";
import { DEFAULT_SIDEBAR_WIDTH } from "./sidebarSizing";
import { ExplorerCollection } from "./ExplorerCollection";
import { ReadingHistoryCache } from "./readingHistoryCache";
import type { ExplorerRow, ListPosition } from "./ExplorerList";
import "./explorer.css";
import "../monitoring/monitoring.css";

const Preview = lazy(() => import("./ExplorerPreview"));
const Settings = lazy(() => import("./ExplorerSettings"));
const ServiceDetail = lazy(() => import("../monitoring/MonitoringServiceDetail"));
const ServiceCreate = lazy(() => import("../monitoring/MonitoringServiceCreate").then(module => ({ default: module.MonitoringServiceCreate })));
const StructureEditor = lazy(() => import("../spatial/SystemStructureEditor").then((module) => ({ default: module.SystemStructureEditor })));
const empty = createEmptySystem();
const subscribeMobile = (listener: () => void) => {
  const media = window.matchMedia("(max-width: 760px)");
  media.addEventListener("change", listener);
  return () => media.removeEventListener("change", listener);
};
const isMobile = () => window.matchMedia("(max-width: 760px)").matches;

export function ExplorerWorkspace({ initialPanel }: { initialPanel?: "settings" } = {}) {
  const { userId, isAuthenticated } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedEntity = searchParams.get("entity");
  const requestedService = searchParams.get("service");
  const requestedReading = searchParams.get("reading");
  const creating = searchParams.get("create") === "monitoring";
  const openedEntity = useRef<string | null>(null);
  const system = useSystemDocument({ isAuthenticated, accountKey: userId });
  const document = system.document ?? empty;
  const index = useMemo(() => buildNavigationIndex(document), [document]);
  const monitoring = useMonitoringServices(isAuthenticated, requestedService ? 5_000 : 20_000);
  const monitoringIndex = useMemo(() => buildMonitoringIndex(document, system.snapshot?.runtime, monitoring.services), [document, system.snapshot?.runtime, monitoring.services]);
  const [rawPreferences, setPreferences] = useState(() => loadExplorerPreferences(userId ?? null));
  const preferences = useMemo(() => {
    if (!system.document) return rawPreferences;
    const validScopes = new Set(index.nodes.keys());
    validScopes.add("system");
    document.groups.forEach((group) => validScopes.add(`catalogue:${group.id}`));
    // Keep archived personal groups intact; only restore an active catalogue scope.
    return validScopes.has(rawPreferences.scopeKey) ? rawPreferences : { ...rawPreferences, scopeKey: "system" };
  }, [system.document, index, rawPreferences, document.groups]);
  const [stored, setStored] = useState(true);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [monitorScope, setMonitorScope] = useState<string>();
  const [panel, setPanel] = useState<"settings" | "collection" | null>(initialPanel ?? (searchParams.get("catalogue") === "settings" ? "settings" : null));
  const [editor, setEditor] = useState<{ kind: SystemEntityKind; id?: string; key: number }>();
  const [mobileOpen, setMobileOpen] = useState(false);
  const mobile = useSyncExternalStore(subscribeMobile, isMobile, () => false);
  const [positions] = useState(() => new Map<string, ListPosition>());
  const explorerToggle = useRef<HTMLButtonElement>(null);
  const dialogOrigin = useRef<HTMLElement | null>(null);
  const history = useRef<string[]>([]);
  const [notice, setNotice] = useState("");
  const [telemetry] = useState(() => new SystemLiveTelemetry());
  const readingHistory = useMemo(() => new ReadingHistoryCache(isAuthenticated ? userId ?? null : null), [isAuthenticated, userId]);
  const scopeKey = preferences.scopeKey === "system" ? index.rootKey : preferences.scopeKey;
  const selected = !requestedService && !creating && selectedKey ? index.nodes.get(selectedKey) : undefined;
  const recordedStreamIds = useMemo(() => new Set(document.streams.flatMap(stream => stream.value_type === "number"
    && (system.snapshot?.runtime.bindings?.[stream.id]?.policy.mode ?? "off") !== "off" ? [stream.id] : [])), [document.streams, system.snapshot?.runtime]);
  const liveStreamIds = useMemo(() => (selected?.streamIds ?? []).filter(id => !recordedStreamIds.has(id)), [selected?.streamIds, recordedStreamIds]);
  const recordedScope = !!selected?.streamIds.length && liveStreamIds.length === 0;
  const selectedService = monitoring.services.find(service => service.id === requestedService);
  const current = index.nodes.get(scopeKey);
  const canonical = document.groups.find((group) => `catalogue:${group.id}` === scopeKey);
  const scopeStreamIds = useMemo(() => {
    const members = canonical?.member_ids;
    return members ? [...new Set(members.flatMap((id) => (index.objectKeys.get(id) ?? [])
      .flatMap((key) => index.nodes.get(key)?.streamIds ?? [])))] : current?.streamIds ?? [];
  }, [canonical, index, current]);
  const canStart = isAuthenticated && system.snapshot?.can_edit === true;
  const revision = system.revision ?? 0;
  const collectionStreamIds = selected?.streamIds ?? scopeStreamIds;
  const scopeInputs = useMemo(() => {
    if (!monitorScope || monitorScope === index.rootKey) return;
    const group = document.groups.find(item => `catalogue:${item.id}` === monitorScope);
    return group ? [...new Set(group.member_ids.flatMap(id => (index.objectKeys.get(id) ?? [])
      .flatMap(key => index.nodes.get(key)?.streamIds ?? [])))] : index.nodes.get(monitorScope)?.streamIds ?? [];
  }, [monitorScope, index, document.groups]);
  const scopedServices = useMemo(() => servicesForScope(monitoring.services, monitoringIndex, scopeInputs), [monitoring.services, monitoringIndex, scopeInputs]);
  const favouriteServices = useMemo(() => new Set((preferences.favourites ?? []).filter(item => item.kind === "service").map(item => item.id)), [preferences.favourites]);
  const favourites = useMemo(() => {
    const services = new Map(monitoring.services.map(service => [service.id, service]));
    const streams = new Map(document.streams.map(stream => [stream.id, stream]));
    return (preferences.favourites ?? []).flatMap(item => {
      const service = item.kind === "service" ? services.get(item.id) : undefined;
      const label = item.kind === "reading" ? streams.get(item.id)?.label : service && serviceName(service, monitoringIndex.inputs.get(service.id) ?? []);
      return label ? [{ ...item, label }] : [];
    });
  }, [preferences.favourites, monitoring.services, document.streams, monitoringIndex]);
  const toggleFavourite = (kind: "service" | "reading", id: string) => setPreferences(previous => toggleExplorerFavourite(previous, kind, id));
  useEffect(() => {
    let active = true;
    const objectId = creating || requestedService ? null : requestedReading ?? requestedEntity;
    if (!objectId) {
      if (openedEntity.current) queueMicrotask(() => {
        if (active) { openedEntity.current = null; setSelectedKey(null); }
      });
      return () => { active = false; };
    }
    if (!system.document || openedEntity.current === objectId) return;
    const entity = document.devices.find((item) => item.id === objectId);
    const references = index.objectKeys.get(objectId) ?? [];
    const nodes = references.flatMap((key) => index.nodes.get(key) ?? []).filter((node) => node.entityKind === (requestedReading ? "stream" : "device"));
    const node = nodes.find((item) => item.connectionId === entity?.connection_id) ?? nodes[0];
    // Resolve incoming browser navigation after the asynchronous catalogue load;
    // cancel stale navigation when the URL or account changes before completion.
    queueMicrotask(() => {
      if (!active) return;
      openedEntity.current = objectId;
      if (!node) { setSelectedKey(null); setNotice(requestedReading ? "Reading not found." : "Entity not found."); return; }
      setNotice("");
      setSelectedKey(node.key);
      setPreferences((previous) => ({ ...previous, scopeKey: node.key }));
      setQuery("");
    });
    return () => { active = false; };
  }, [system.document, requestedEntity, requestedReading, requestedService, creating, document.devices, index]);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "k") return;
      if (mobile ? mobileOpen : preferences.sidebarOpen) return;
      event.preventDefault();
      if (mobile) setMobileOpen(true);
      else setPreferences((previous) => ({ ...previous, sidebarOpen: true }));
      requestAnimationFrame(() => requestAnimationFrame(() => window.document.querySelector<HTMLInputElement>(".ex-search input")?.focus()));
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [mobile, mobileOpen, preferences.sidebarOpen]);
  useEffect(() => {
    if (!system.document) return;
    const timeout = window.setTimeout(() => setStored(saveExplorerPreferences(userId ?? null, preferences)), 150);
    const persist = () => saveExplorerPreferences(userId ?? null, preferences);
    window.addEventListener("pagehide", persist);
    return () => { clearTimeout(timeout); window.removeEventListener("pagehide", persist); };
  }, [preferences, userId, system.document]);
  useEffect(() => {
    telemetry.configure(document, revision, isAuthenticated ? String(userId ?? "signed-in") : "", canStart);
  }, [telemetry, document, revision, isAuthenticated, userId, canStart]);
  useEffect(() => () => telemetry.stop(), [telemetry]);
  useEffect(() => { telemetry.setPriority(selected?.objectId ?? null); }, [telemetry, selected?.objectId]);
  useEffect(() => { telemetry.setScope(liveStreamIds); }, [telemetry, liveStreamIds, document]);
  useEffect(() => {
    const visibility = () => window.document.hidden ? telemetry.pause() : telemetry.resume();
    const leave = () => telemetry.stop();
    window.document.addEventListener("visibilitychange", visibility);
    window.addEventListener("pagehide", leave);
    return () => { window.document.removeEventListener("visibilitychange", visibility); window.removeEventListener("pagehide", leave); };
  }, [telemetry]);
  const streamLabels = useMemo(() => new Map(document.streams.map((stream) => [stream.id, stream.label])), [document.streams]);
  const rows = useMemo<ExplorerRow[]>(() => {
    if (deferredQuery.trim()) return searchNavigation(index, deferredQuery).map((node) => ({ node,
      label: node.entityKind === "stream" ? streamLabels.get(node.objectId ?? "") ?? node.label : node.label,
      detail: navigationTrail(index, node.key).slice(1, -1).map((ancestor) => ancestor.label).join(" / ") || "Catalogue" }));
    const members = canonical?.member_ids;
    if (members) return members.flatMap((id) => {
      const key = index.objectKeys.get(id)?.[0];
      const node = key ? index.nodes.get(key) : undefined;
      return node ? [{ node, label: node.entityKind === "stream" ? streamLabels.get(id) ?? node.label : node.label,
        detail: navigationTrail(index, node.key).slice(1, -1).map((ancestor) => ancestor.label).join(" / "), color: canonical?.color }] : [];
    });
    return navigationRows(index, scopeKey).map((row) => ({ ...row,
      detail: row.node.entityKind === "stream" ? streamLabels.get(row.node.objectId ?? "") : undefined }));
  }, [index, deferredQuery, scopeKey, canonical, streamLabels]);
  const go = (key: string, remember = true) => {
    if (remember && key !== scopeKey) {
      if (history.current.length >= 128) history.current.shift();
      history.current.push(scopeKey);
    }
    setPreferences((previous) => ({ ...previous, scopeKey: key })); setQuery("");
    setMonitorScope(key);
  };
  const back = () => {
    if (query) { setQuery(""); return; }
    const previous = history.current.pop();
    go(previous ?? current?.parentKey ?? index.rootKey, false);
  };
  const changeView = (view?: { service?: string; reading?: string; create?: string; target?: string }) => {
    openedEntity.current = null;
    const next = new URLSearchParams(searchParams);
    ["entity", "reading", "service", "create", "target", "tab", "stream"].forEach(key => next.delete(key));
    Object.entries(view ?? {}).forEach(([key, value]) => { if (value) next.set(key, value); });
    setSearchParams(next);
    setSelectedKey(null); setMobileOpen(false);
  };
  const openService = (id: string) => changeView({ service: id });
  const createService = () => {
    const inputs = selected?.streamIds ?? scopeInputs ?? [];
    const targets = [...new Set(inputs.flatMap(id => system.snapshot?.runtime.bindings?.[id]?.entity_id ?? []))];
    changeView({ create: "monitoring", ...(selected?.entityKind === "stream" ? { reading: selected.objectId }
      : inputs.length === 1 ? { reading: inputs[0] } : targets.length === 1 ? { target: targets[0] } : {}) });
  };
  const open = (node: ExplorerNode) => {
    if (node.children.length) { go(node.key); return; }
    if (query || canonical) go(node.parentKey ?? index.rootKey);
    changeView();
    setSelectedKey(node.key); setMobileOpen(false);
  };
  const closeSelection = () => {
    setSelectedKey(null); setMobileOpen(false);
    changeView();
  };
  const openEditor = (kind: SystemEntityKind, id?: string) => {
    if (!panel) dialogOrigin.current = window.document.activeElement as HTMLElement;
    setPanel(null); setEditor({ kind, id, key: Date.now() });
  };
  const rename = async (kind: SystemEntityKind, id: string, name: string) => {
    if (!(await system.rename(kind, id, name))) throw new Error("The name could not be saved.");
  };
  const importConfiguration = async (next: SystemDocument, baseline: number) => {
    if (!(await system.save(next, baseline))) return false;
    setPreferences((previous) => ({ ...previous, scopeKey: index.rootKey }));
    setSelectedKey(null); history.current = []; positions.clear();
    setNotice("Catalogue imported and saved."); return true;
  };
  const exportConfiguration = async () => {
    const saved = await system.refresh();
    if (!saved) { setNotice("The saved catalogue could not be read. Try again."); return; }
    const contents = serializeSystemDocument(saved);
    const url = URL.createObjectURL(new Blob([contents], { type: "application/json" }));
    const anchor = window.document.createElement("a"); anchor.href = url;
    anchor.download = "aberration-system.json"; anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000); setNotice("Saved catalogue exported.");
  };
  const scopeTitle = current?.kind === "topic" ? navigationTrail(index, scopeKey).filter((node) => node.kind === "topic").map((node) => node.label).join("/") : current?.label;
  const sidebar = <ExplorerSidebar index={index} scopeKey={scopeKey} title={canonical?.label ?? scopeTitle ?? document.label}
    catalogueGroups={document.groups} rows={rows} query={query} resultsQuery={deferredQuery} selectedKey={selectedKey}
    positions={positions} loading={system.status === "loading"} onQuery={setQuery} onScope={go} onOpen={open} onBack={back}
    onInspect={() => { if (current) { changeView(); setSelectedKey(current.key); } }}
    favourites={favourites} onFavourite={(kind, id) => kind === "service" ? openService(id) : changeView({ reading: id })}
    onSettings={() => { dialogOrigin.current = window.document.activeElement as HTMLElement; setPanel("settings"); setMobileOpen(false); }} onWorkspace={() => { closeSelection(); setMonitorScope(undefined); }}
    onDismiss={mobile ? () => setMobileOpen(false) : undefined} />;
  return <div className={`ex-shell${!mobile && !preferences.sidebarOpen ? " ex-sidebar-hidden" : ""}`}
    style={{ "--ex-sidebar-width": `${preferences.sidebarWidth ?? DEFAULT_SIDEBAR_WIDTH}px` } as CSSProperties}>
    {!mobile && preferences.sidebarOpen && <div className="ex-sidebar-dock">{sidebar}
      <ExplorerSidebarResize width={preferences.sidebarWidth ?? DEFAULT_SIDEBAR_WIDTH}
        onCommit={(sidebarWidth) => setPreferences((previous) => ({ ...previous, sidebarWidth }))} />
    </div>}
    <main className="ex-main" aria-label="Monitoring workspace">
      <AppHeader leading={<button ref={explorerToggle} className="app-icon-button" aria-label={mobile ? "Open explorer" : "Toggle explorer"} onClick={() => mobile ? setMobileOpen(true)
          : setPreferences((previous) => ({ ...previous, sidebarOpen: !previous.sidebarOpen }))}>{mobile ? <Menu size={19} /> : <PanelLeft size={18} />}</button>} />
      <div className="ex-main-content">
        <div className="ex-workspace-heading"><h1>Monitoring</h1>
          <div className="ex-workspace-actions">{selected && <><button className="ex-collection-action" disabled={!system.document || system.saving || !collectionStreamIds.length}
            onClick={() => { dialogOrigin.current = window.document.activeElement as HTMLElement; setPanel("collection"); }}>Collection</button>
          {!recordedScope && <SystemLiveControls telemetry={telemetry} canStart={canStart} canView={isAuthenticated && !!system.snapshot} disabled={system.saving || !system.document} />}</>}
          {system.canEdit && !creating && <button className="mn-primary" disabled={system.saving || !system.document || !monitoring.ready} onClick={createService}><Plus size={15} />Create service</button>}</div></div>
        {system.status === "sign-in-required" && <p className="ex-banner">Sign in to load the catalogue. <Link to="/login">Sign in <ArrowUpRight size={12} /></Link></p>}
        {system.error && !editor && <p className="ex-banner ex-error" role="alert">{system.error}<button onClick={() => void system.refresh()}>Retry</button></p>}
        {!stored && <p className="ex-banner ex-error" role="status">Browser storage is unavailable. Your navigation will last for this session.</p>}
        {creating ? <Suspense fallback={<p className="ex-muted" role="status">Opening setup…</p>}>
          {system.canEdit ? <ServiceCreate key={`${searchParams.get("target") ?? (requestedReading ? system.snapshot?.runtime.bindings?.[requestedReading]?.entity_id : "")}:${requestedReading ?? ""}`} targets={monitoringIndex.targets} services={monitoring.services}
            initialTarget={searchParams.get("target") ?? (requestedReading ? system.snapshot?.runtime.bindings?.[requestedReading]?.entity_id : undefined)} initialReading={requestedReading ?? undefined}
            byStream={monitoringIndex.byStream}
            collectionReady={system.snapshot?.runtime.collection?.status === "applied"}
            collection={ids => <ExplorerCollection streamIds={ids} runtime={system.snapshot?.runtime} canMonitor={false}
              revision={revision} canEdit={system.canEdit} saving={system.saving} onApply={system.applyCollection} onRefresh={system.refreshRuntime} onStatus={system.updateRuntime} />}
            onStarted={async id => { await monitoring.reload(); if (id) openService(id); else closeSelection(); }} onBack={closeSelection} />
            : <p className="ex-muted">{system.status === "loading" ? "Loading…" : "An administrator can create monitoring services."}</p>}
        </Suspense> : requestedService ? selectedService ? <Suspense fallback={<p className="ex-muted" role="status">Opening service…</p>}>
          <ServiceDetail key={selectedService.id} service={selectedService} inputs={monitoringIndex.inputs.get(selectedService.id) ?? []} document={document} historyCache={readingHistory}
            canEdit={system.canEdit} favourite={favouriteServices.has(selectedService.id)} onFavourite={() => toggleFavourite("service", selectedService.id)}
            onRename={name => monitoring.rename(selectedService.id, name)} onBack={closeSelection}
            onDeleted={async () => { monitoring.remove(selectedService.id); closeSelection(); await monitoring.reload(); }} />
        </Suspense> : <div className="mn-empty"><p>{monitoring.error || (!monitoring.ready ? "Loading service…" : "Service not found.")}</p>
          <button onClick={closeSelection}>Monitoring</button>{monitoring.error && <button onClick={() => void monitoring.reload()}>Retry</button>}</div>
        : selected ? <Suspense fallback={<p className="ex-muted" role="status">Opening preview…</p>}><Preview key={selected.key} node={selected} index={index}
          document={document} telemetry={telemetry} historyCache={readingHistory} canEdit={system.canEdit} saving={system.saving} error={system.error} onRename={rename}
          onEdit={openEditor} onClose={closeSelection} runtime={system.snapshot?.runtime}
          favourite={(preferences.favourites ?? []).some(item => item.kind === "reading" && item.id === selected.objectId)} onFavourite={id => toggleFavourite("reading", id)}
          collectionControls={<ExplorerCollection key={selected.key} streamIds={selected.streamIds} runtime={system.snapshot?.runtime}
            canMonitor={selected.streamIds.length === 1 && document.streams.find((stream) => stream.id === selected.streamIds[0])?.value_type === "number"}
            revision={revision} canEdit={system.canEdit} saving={system.saving} onApply={system.applyCollection} onRefresh={system.refreshRuntime} onStatus={system.updateRuntime} />} />
        </Suspense> : <>{scopeInputs && <div className="mn-scope"><span>{document.groups.find(group => `catalogue:${group.id}` === monitorScope)?.label ?? index.nodes.get(monitorScope ?? "")?.label}</span>
          <button onClick={() => setMonitorScope(undefined)}>All services <X size={12} /></button></div>}
          {isAuthenticated && <MonitoringServiceList services={scopedServices} index={monitoringIndex} ready={monitoring.ready} error={monitoring.error}
            favourites={favouriteServices} onFavourite={id => toggleFavourite("service", id)} onOpen={openService} onRetry={() => void monitoring.reload()} />}</>}
        {notice && <p className="ex-notice" role="status">{notice}<button aria-label="Dismiss notice" onClick={() => setNotice("")}><X size={14} /></button></p>}
      </div>
    </main>
    <Dialog.Root open={mobile && mobileOpen} onOpenChange={setMobileOpen}><Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" />
      <Dialog.Content className="ex-mobile-sidebar" onCloseAutoFocus={(event) => { event.preventDefault(); if (!panel) explorerToggle.current?.focus(); }}><Dialog.Title className="ex-sr-only">System explorer</Dialog.Title>
        <Dialog.Description className="ex-sr-only">Browse your catalogue or search for a reading.</Dialog.Description>{sidebar}</Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={!!panel || !!editor} onOpenChange={(value) => { if (!value && !system.saving) { setPanel(null); setEditor(undefined); } }}>
      <Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" /><Dialog.Content className="ex-dialog" onEscapeKeyDown={(event) => { if (system.saving) event.preventDefault(); }}
        onCloseAutoFocus={(event) => { event.preventDefault(); (dialogOrigin.current?.isConnected ? dialogOrigin.current : explorerToggle.current)?.focus(); }}>
        <header><Dialog.Title>{editor ? "Edit catalogue" : panel === "collection" ? "Collection" : "Catalogue settings"}</Dialog.Title>
          <Dialog.Close className="ex-icon-button" disabled={system.saving} aria-label="Close settings"><X size={18} /></Dialog.Close></header>
        <Dialog.Description className="ex-sr-only">Manage the saved system definition.</Dialog.Description>
        <Suspense fallback={<p className="ex-muted">Loading…</p>}>
          {editor ? <StructureEditor key={editor.key} document={document} revision={revision} kind={editor.kind} entityId={editor.id}
            canEdit={system.canEdit} saving={system.saving} saveError={system.error} onSave={system.save} onDone={() => setEditor(undefined)} />
            : panel === "collection" ? <ExplorerCollection
              key={selected?.key ?? scopeKey} streamIds={collectionStreamIds} runtime={system.snapshot?.runtime} revision={revision} canEdit={system.canEdit} saving={system.saving}
              onApply={system.applyCollection} onRefresh={system.refreshRuntime} onStatus={system.updateRuntime} /> : <Settings document={document}
              revision={revision} canEdit={system.canEdit} saving={system.saving} error={system.error}
              onImport={importConfiguration} onExport={exportConfiguration} onCreate={openEditor} />}
        </Suspense>
      </Dialog.Content></Dialog.Portal>
    </Dialog.Root>
  </div>;
}
