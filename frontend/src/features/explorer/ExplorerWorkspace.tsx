import { lazy, Suspense, useEffect, useMemo } from "react";
import { ArrowLeft, Info, Plus } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { rememberNavigation } from "@/lib/navigation-draft";
import { SystemLiveControls } from "../catalogue/SystemLiveControls";
import { collectionApplied } from "@/domain/system/collectionRules";
import { MonitoringServiceList } from "../monitoring/MonitoringServiceList";
import { monitoringNavigationKey, resetView } from "@/domain/monitoring/monitoringView";
import { buildMonitoringIndex, readingTargetId, serviceName, servicesForScope } from "@/domain/monitoring/serviceModel";
import { useMonitoringServices } from "@/domain/monitoring/useMonitoringServices";
import { useCatalogue } from "../workspace/catalogue-context";
import { SourceScope } from "../workspace/SourceScope";
import { CopyToDojo } from "../dojo/CopyToDojo";
import { useDesignTest } from "../dojo/designTest";
import { DesignTestContext } from "../pipelines/designTest";
import { catalogueSelectionLabel, withCatalogueSource } from "../workspace/catalogue-navigation";
import "../monitoring/monitoring.css";
import { setSourceAppearance } from "@/domain/system/sourceAppearance";

const Preview = lazy(() => import("../readings/ExplorerPreview"));
const ServiceDetail = lazy(() => import("../monitoring/MonitoringServiceDetail"));
const ServiceCreate = lazy(() => import("../monitoring/MonitoringServiceCreate").then(module => ({ default: module.MonitoringServiceCreate })));
const Pipelines = lazy(() => import("../pipelines/PipelineWorkspace"));
const RetainedPipeline = lazy(() => import("../pipelines/PipelineRunView"));

export function ExplorerWorkspace() {
  const { userId, isAuthenticated, can } = useAuth();
  const manageMonitors = can("manage_monitors");
  const designTest = useDesignTest();
  const [params, setParams] = useSearchParams();
  const { system, document, index, selected, selectionMissing, streamIds, liveStreamIds, telemetry, history,
    favourites: starred, toggleFavourite, openEditor, sectionHref } = useCatalogue();
  const requestedService = params.get("service");
  const requestedReading = params.get("reading") ?? undefined;
  const requestedStream = requestedReading ? document.readings.find(stream => stream.id === requestedReading) : undefined;
  const initialTarget = params.get("target") ?? (requestedStream && readingTargetId(requestedStream));
  const creating = params.get("create") === "monitoring";
  const monitoring = useMonitoringServices(isAuthenticated, requestedService ? 5_000 : 20_000, requestedService ?? params.get("replace") ?? undefined);
  const pipelineView = !!params.get("pipeline") || params.get("view") === "pipelines" || creating && monitoring.authoringEnabled;
  const loadingCreation = creating && !params.get("pipeline") && params.get("view") !== "pipelines" && isAuthenticated
    && (!monitoring.ready || !system.document || system.status === "loading");
  const creationError = monitoring.error || system.error;
  const monitoringIndex = useMemo(() => buildMonitoringIndex(document, system.snapshot?.runtime, monitoring.services),
    [document, system.snapshot?.runtime, monitoring.services]);
  const scopedServices = useMemo(() => servicesForScope(monitoring.services, monitoringIndex, streamIds),
    [monitoring.services, monitoringIndex, streamIds]);
  const selectedService = monitoring.services.find(service => service.id === requestedService);
  const favourites = useMemo(() => new Set(starred.filter(item => item.kind === "monitor").map(item => item.id)), [starred]);
  const preview = selected && (selected.entityKind === "stream" || params.has("entity") || params.get("inspect") === "source");
  const previewReadings = useMemo(() => {
    const ids = new Set(streamIds ?? []);
    return document.readings.filter(stream => ids.has(stream.id));
  }, [document.readings, streamIds]);
  const readingDetail = selected?.entityKind === "stream" && !creating && !requestedService && !pipelineView;
  // Service detail and setup carry their own breadcrumb and heading.
  const ownHeading = !loadingCreation && !(selectionMissing && !pipelineView)
    && (pipelineView || creating && manageMonitors || !!requestedService && !!selectedService);
  const selectedLabel = selected && (selected.entityKind === "stream"
    ? document.readings.find(stream => stream.id === selected.objectId)?.label ?? selected.label : selected.label);
  let title = catalogueSelectionLabel(document, selected);
  if (loadingCreation) title = "New service";
  else if (selectionMissing && !pipelineView) title = "Source not found";
  else if (pipelineView) {
    title = params.get("pipeline") ? (params.has("activation") ? "Starting service" : "Template")
      : params.get("view") === "pipelines" ? "Templates" : params.has("replace") ? "Update service" : "New service";
  } else if (creating) title = "New service";
  else if (selectedService) title = serviceName(selectedService, monitoringIndex.inputs.get(selectedService.id) ?? []);
  else if (requestedService) title = params.get("tab") === "pipeline" ? "Retained pipeline"
    : monitoring.ready ? "Service not found" : "Monitoring service";
  useDocumentTitle(title, "Monitoring");
  useEffect(() => {
    rememberNavigation(monitoringNavigationKey(userId), `/${params.size ? `?${params}` : ""}`);
  }, [userId, params]);

  const changeView = (view?: Record<string, string | undefined>) => setParams(resetView(params, selected?.key, view));
  const openService = (id: string) => changeView({ service: id });
  const closeView = () => changeView();
  const createService = () => {
    const inputs = streamIds ?? [];
    const chosen = new Set(inputs);
    const targets = [...new Set(document.readings.filter(stream => chosen.has(stream.id)).map(readingTargetId))];
    changeView({ create: "monitoring", ...(selected?.entityKind === "stream" ? { reading: selected.objectId }
      : inputs.length === 1 ? { reading: inputs[0] } : targets.length === 1 ? { target: targets[0] } : {}) });
  };
  const rename = async (kind: Parameters<typeof system.rename>[0], id: string, name: string) => {
    if (!await system.rename(kind, id, name)) throw new Error("The name could not be saved.");
  };

  const renderView = () => {
    if (loadingCreation) return <p className={creationError ? "ex-banner ex-error" : "ex-muted"} role={creationError ? "alert" : "status"}>
      {creationError || "Opening monitoring setup…"}{creationError && <button onClick={() => void Promise.allSettled([monitoring.reload(), system.refresh()])}>Retry</button>}
    </p>;
    if (selectionMissing && !pipelineView) return <p role="alert">{params.has("reading") ? "Reading not found." : params.has("entity") ? "Device not found." : "Source not found."}</p>;
    if (pipelineView) return <Suspense fallback={<p className="ex-muted" role="status">Opening pipelines…</p>}>
      <DesignTestContext.Provider value={designTest}><Pipelines services={monitoring.services} index={monitoringIndex} canEdit={manageMonitors}
        initialTarget={initialTarget} initialReading={requestedReading}
        onBack={closeView} onStarted={async id => { await monitoring.reload(); openService(id); }} /></DesignTestContext.Provider></Suspense>;
    if (creating) return <Suspense fallback={<p className="ex-muted" role="status">Opening setup…</p>}>
      {manageMonitors ? <ServiceCreate key={`${initialTarget ?? ""}:${requestedReading ?? ""}`}
        targets={monitoringIndex.targets} services={monitoring.services}
        initialTarget={initialTarget}
        initialReading={requestedReading} byStream={monitoringIndex.byStream}
        collectionReady={collectionApplied(system.snapshot?.runtime)} document={document}
        draftKey={`service-setup:${userId}:${params.get("target") ?? ""}:${requestedReading ?? ""}`}
        onStarted={async id => { await monitoring.reload(); if (id) openService(id); else closeView(); }} onBack={closeView} />
        : <p className="ex-muted">{system.status === "loading" ? "Loading…" : "Creating monitoring services needs the Manage monitors permission."}</p>}
    </Suspense>;
    if (requestedService && selectedService) return <Suspense fallback={<p className="ex-muted" role="status">Opening service…</p>}>
      <ServiceDetail key={selectedService.id} service={selectedService} inputs={monitoringIndex.inputs.get(selectedService.id) ?? []}
        document={document} historyCache={history} canEdit={manageMonitors} favourite={favourites.has(selectedService.id)}
        pipelineState={monitoring.pipelineState ?? undefined} onFavourite={() => toggleFavourite("monitor", selectedService.id)} onRename={name => monitoring.rename(selectedService.id, name)} onBack={closeView}
        onDeleted={async () => { monitoring.remove(selectedService.id); closeView(); await monitoring.reload(); }} />
    </Suspense>;
    // A retained run outlives its service row.
    if (requestedService && monitoring.ready && params.get("tab") === "pipeline") return <Suspense fallback={<p role="status">Opening retained run…</p>}><RetainedPipeline key={requestedService} serviceId={requestedService} canEdit={manageMonitors} replaceable={false} /></Suspense>;
    if (requestedService) return <div className="mn-empty"><p>{monitoring.error || (!monitoring.ready ? "Loading service…" : "Service not found.")}</p>
      <button onClick={closeView}><ArrowLeft size={14} aria-hidden="true" />All services</button>{monitoring.error && <button onClick={() => void monitoring.reload()}>Retry</button>}
    </div>;
    return <>
      {preview && <Suspense fallback={<p className="ex-muted" role="status">Opening preview…</p>}><Preview key={selected.key} node={{ ...selected, streamIds: streamIds ?? [] }}
        index={index} document={document} telemetry={telemetry} historyCache={history} canEdit={system.canEdit} saving={system.saving}
        error={system.error} onRename={rename} onEdit={openEditor}
        onAppearanceChange={appearance => system.save(setSourceAppearance(document, selected, appearance), system.revision ?? 0)}
        runtime={system.snapshot?.runtime} collapseDefinition favourite={starred.some(item => item.kind === "reading" && item.id === selected.objectId)}
        onFavourite={id => toggleFavourite("reading", id)}
        actions={<CopyToDojo compact scope={selectedLabel ?? selected.label} readings={previewReadings} />}
        collectionControls={selected.entityKind !== "stream" && !!streamIds?.length && <p className="ex-muted">
          Recording enabled for {streamIds.filter(id => {
            const policy = system.snapshot?.runtime.bindings?.[id]?.policy;
            return policy && policy.mode !== "off";
          }).length} of {streamIds.length} readings</p>} />
      </Suspense>}
      {isAuthenticated && <MonitoringServiceList draftKey={`monitoring:${userId}:services`} services={scopedServices}
        index={monitoringIndex} ready={monitoring.ready} error={monitoring.error} favourites={favourites}
        serviceHref={id => withCatalogueSource(`/?service=${encodeURIComponent(id)}`, selected)}
        onFavourite={id => toggleFavourite("monitor", id)} onOpen={openService} onRetry={() => void monitoring.reload()} />}
    </>;
  };

  return <main className="ex-main-content" aria-label="Monitoring workspace">
    {!ownHeading && <><div className="ex-workspace-heading"><h1>Monitoring</h1>
      <div className="ex-workspace-actions">
        {readingDetail && <SourceScope compact />}
        {selected && !creating && !requestedService && <>
          {!preview && <><Link className="ex-collection-action" to={sectionHref("/sources")}>Configure in Sources</Link>
            <button className="ex-collection-action" onClick={() => changeView({ inspect: "source" })}><Info size={15} aria-hidden="true" />Inspect source</button></>}
          {preview && selected.entityKind !== "stream" && <button className="ex-collection-action" onClick={closeView}><Info size={15} aria-hidden="true" />Hide source details</button>}
          {liveStreamIds.length > 0 && <SystemLiveControls telemetry={telemetry} canStart={system.canEdit} canView={!!system.snapshot} disabled={system.saving} />}
        </>}
        {manageMonitors && !creating && !pipelineView && <button className="mn-primary" disabled={system.saving || !system.document || !monitoring.ready} onClick={createService}>
          <Plus size={15} />Create
        </button>}
      </div>
    </div>
    {!readingDetail && <SourceScope />}</>}
    {system.status === "sign-in-required" && <p className="ex-banner">Sign in to load the catalogue. <Link to="/login">Sign in</Link></p>}
    {system.error && <p className="ex-banner ex-error" role="alert">{system.error}<button onClick={() => void system.refresh()}>Retry</button></p>}
    {renderView()}
  </main>;
}
