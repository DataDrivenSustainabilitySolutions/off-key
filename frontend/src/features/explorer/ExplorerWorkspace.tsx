import { lazy, Suspense, useEffect, useMemo } from "react";
import { GitBranch, Info, Plus } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { rememberNavigation } from "@/lib/navigation-draft";
import { SystemLiveControls } from "../catalogue/SystemLiveControls";
import { sourceHref } from "../catalogue/collectionRules";
import { MonitoringServiceList } from "../monitoring/MonitoringServiceList";
import { buildMonitoringIndex, servicesForScope } from "../monitoring/serviceModel";
import { useMonitoringServices } from "../monitoring/useMonitoringServices";
import { useCatalogue } from "../workspace/catalogue-context";
import { SourceScope } from "../workspace/SourceScope";
import { withCatalogueSource } from "../workspace/catalogue-navigation";
import type { PipelineState } from "../pipelines/PipelineDiagnostics";
import "../monitoring/monitoring.css";

const Preview = lazy(() => import("./ExplorerPreview"));
const ServiceDetail = lazy(() => import("../monitoring/MonitoringServiceDetail"));
const ServiceCreate = lazy(() => import("../monitoring/MonitoringServiceCreate").then(module => ({ default: module.MonitoringServiceCreate })));
const Pipelines = lazy(() => import("../pipelines/PipelineWorkspace"));
const RetainedPipeline = lazy(() => import("../pipelines/PipelineRunView"));

export function ExplorerWorkspace() {
  const { userId, isAuthenticated } = useAuth();
  const [params, setParams] = useSearchParams();
  const { system, document, index, selected, selectionMissing, streamIds, liveStreamIds, telemetry, history,
    preferences, toggleFavourite, openEditor, selectSource, sectionHref } = useCatalogue();
  const requestedService = params.get("service");
  const requestedReading = params.get("reading") ?? (selected?.entityKind === "stream" ? selected.objectId : undefined);
  const creating = params.get("create") === "monitoring";
  const monitoring = useMonitoringServices(isAuthenticated, requestedService ? 5_000 : 20_000, requestedService ?? params.get("replace") ?? undefined);
  const pipelineView = !!params.get("pipeline") || params.get("view") === "pipelines" || creating && monitoring.authoringEnabled;
  const monitoringIndex = useMemo(() => buildMonitoringIndex(document, system.snapshot?.runtime, monitoring.services),
    [document, system.snapshot?.runtime, monitoring.services]);
  const scopedServices = useMemo(() => servicesForScope(monitoring.services, monitoringIndex, streamIds),
    [monitoring.services, monitoringIndex, streamIds]);
  const selectedService = monitoring.services.find(service => service.id === requestedService);
  const favourites = useMemo(() => new Set((preferences.favourites ?? []).filter(item => item.kind === "service").map(item => item.id)), [preferences.favourites]);
  const preview = selected && (selected.entityKind === "stream" || params.has("entity") || params.get("inspect") === "source");
  useEffect(() => {
    rememberNavigation(`monitoring:${userId}:url`, `/${params.size ? `?${params}` : ""}`);
  }, [userId, params]);

  const changeView = (view?: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    ["entity", "reading", "broker", "topic", "service", "create", "target", "tab", "stream", "inspect", "pipeline", "view", "revision", "activation", "replace"].forEach(key => next.delete(key));
    if (selected) next.set("source", selected.key);
    Object.entries(view ?? {}).forEach(([key, value]) => { if (value) next.set(key, value); });
    setParams(next);
  };
  const openService = (id: string) => changeView({ service: id });
  const closeView = () => changeView();
  const createService = () => {
    const inputs = streamIds ?? [];
    const targets = [...new Set(inputs.flatMap(id => system.snapshot?.runtime.bindings?.[id]?.entity_id ?? []))];
    changeView({ create: "monitoring", ...(selected?.entityKind === "stream" ? { reading: selected.objectId }
      : inputs.length === 1 ? { reading: inputs[0] } : targets.length === 1 ? { target: targets[0] } : {}) });
  };
  const rename = async (kind: Parameters<typeof system.rename>[0], id: string, name: string) => {
    if (!await system.rename(kind, id, name)) throw new Error("The name could not be saved.");
  };

  return <main className="ex-main-content" aria-label="Monitoring workspace">
    <div className="ex-workspace-heading"><h1>Monitoring</h1>
      <div className="ex-workspace-actions">
        {!pipelineView && <button onClick={() => changeView({ view: "pipelines" })}><GitBranch size={15} />Pipelines</button>}
        {selected && !creating && !requestedService && <><Link className="ex-collection-action" to={sectionHref("/sources")}>Configure in Sources</Link>
          {!preview && <button onClick={() => changeView({ inspect: "source" })}><Info size={15} />Inspect source</button>}
          {liveStreamIds.length > 0 && <SystemLiveControls telemetry={telemetry} canStart={system.canEdit} canView={!!system.snapshot} disabled={system.saving} />}
        </>}
        {system.canEdit && !creating && !pipelineView && <button className="mn-primary" disabled={system.saving || !system.document || !monitoring.ready} onClick={createService}>
          <Plus size={15} />Create service
        </button>}
      </div>
    </div>
    <SourceScope />
    {system.status === "sign-in-required" && <p className="ex-banner">Sign in to load the catalogue. <Link to="/login">Sign in</Link></p>}
    {system.error && <p className="ex-banner ex-error" role="alert">{system.error}<button onClick={() => void system.refresh()}>Retry</button></p>}
    {selectionMissing && !pipelineView ? <p role="alert">{params.has("reading") ? "Reading not found." : params.has("entity") ? "Entity not found." : "Source not found."}</p>
      : pipelineView ? <Suspense fallback={<p className="ex-muted" role="status">Opening pipelines…</p>}><Pipelines services={monitoring.services} index={monitoringIndex} canEdit={system.canEdit}
        initialTarget={params.get("target") ?? (requestedReading ? system.snapshot?.runtime.bindings?.[requestedReading]?.entity_id : undefined)} initialReading={requestedReading ?? undefined}
        onBack={closeView} onStarted={async id => { await monitoring.reload(); openService(id); }} /></Suspense>
      : creating ? <Suspense fallback={<p className="ex-muted" role="status">Opening setup…</p>}>
        {system.canEdit ? <ServiceCreate key={`${params.get("target") ?? (requestedReading ? system.snapshot?.runtime.bindings?.[requestedReading]?.entity_id : "")}:${requestedReading ?? ""}`}
          targets={monitoringIndex.targets} services={monitoring.services}
          initialTarget={params.get("target") ?? (requestedReading ? system.snapshot?.runtime.bindings?.[requestedReading]?.entity_id : undefined)}
          initialReading={requestedReading ?? undefined} byStream={monitoringIndex.byStream}
          collectionReady={system.snapshot?.runtime.collection?.status === "applied"} document={document}
          draftKey={`service-setup:${userId}:${params.get("target") ?? ""}:${requestedReading ?? ""}`}
          onStarted={async id => { await monitoring.reload(); if (id) openService(id); else closeView(); }} onBack={closeView} />
          : <p className="ex-muted">{system.status === "loading" ? "Loading…" : "An administrator can create monitoring services."}</p>}
      </Suspense> : requestedService ? selectedService ? <Suspense fallback={<p className="ex-muted" role="status">Opening service…</p>}>
        <ServiceDetail key={selectedService.id} service={selectedService} inputs={monitoringIndex.inputs.get(selectedService.id) ?? []}
          document={document} historyCache={history} canEdit={system.canEdit} favourite={favourites.has(selectedService.id)}
          pipelineState={monitoring.pipelineState as unknown as PipelineState | undefined} onFavourite={() => toggleFavourite("service", selectedService.id)} onRename={name => monitoring.rename(selectedService.id, name)} onBack={closeView}
          onDeleted={async () => { monitoring.remove(selectedService.id); closeView(); await monitoring.reload(); }} />
      </Suspense> : monitoring.ready && params.get("tab") === "pipeline" ? <Suspense fallback={<p role="status">Opening retained run…</p>}><RetainedPipeline serviceId={requestedService} canEdit={system.canEdit} replaceable={false} /></Suspense>
      : <div className="mn-empty"><p>{monitoring.error || (!monitoring.ready ? "Loading service…" : "Service not found.")}</p>
        <button onClick={closeView}>Monitoring</button>{monitoring.error && <button onClick={() => void monitoring.reload()}>Retry</button>}
      </div> : <>
        {preview && <Suspense fallback={<p className="ex-muted" role="status">Opening preview…</p>}><Preview key={selected.key} node={{ ...selected, streamIds: streamIds ?? [] }}
          index={index} document={document} telemetry={telemetry} historyCache={history} canEdit={system.canEdit} saving={system.saving}
          error={system.error} onRename={rename} onEdit={openEditor} onClose={() => selected.entityKind === "stream" ? selectSource(null) : closeView()}
          runtime={system.snapshot?.runtime} favourite={(preferences.favourites ?? []).some(item => item.kind === "reading" && item.id === selected.objectId)}
          onFavourite={id => toggleFavourite("reading", id)}
          collectionControls={<p className="ex-muted">Collection: {(streamIds ?? []).filter(id => system.snapshot?.runtime.bindings?.[id]?.policy.mode !== "off").length}
            {" "}of {streamIds?.length ?? 0} enabled · <Link to={sourceHref(streamIds ?? [], document)}>Configure in Sources</Link></p>} />
        </Suspense>}
        {isAuthenticated && <MonitoringServiceList draftKey={`monitoring:${userId}:services`} services={scopedServices}
          index={monitoringIndex} ready={monitoring.ready} error={monitoring.error} favourites={favourites}
          serviceHref={id => withCatalogueSource(`/?service=${encodeURIComponent(id)}`, selected)}
          onFavourite={id => toggleFavourite("service", id)} onOpen={openService} onRetry={() => void monitoring.reload()} />}
      </>}
  </main>;
}
