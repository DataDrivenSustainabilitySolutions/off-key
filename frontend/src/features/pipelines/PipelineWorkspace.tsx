import { useEffect, useState } from "react";
import { Breadcrumb } from "@/components/Breadcrumb";
import { useSearchParams } from "react-router-dom";
import { getErrorMessage } from "@/lib/errors";
import type { ActiveService } from "@/types/monitoring";
import type { MonitoringIndex } from "@/domain/monitoring/serviceModel";
import { useCatalogue } from "../workspace/catalogue-context";
import { collectionApplied } from "@/domain/system/collectionRules";
import { predecessorEntity } from "./bindings";
import { pipelinesApi } from "./api";
import type { PipelineCatalog, PipelineServiceView } from "./contracts";
import { PipelineLibrary } from "./PipelineLibrary";
import { PipelineCreate } from "./PipelineCreate";
import PipelineEditor from "./PipelineEditor";
import { createPipeline, dropReplacement, openPipeline, setActivation, setRevision, showLibrary } from "@/domain/monitoring/monitoringView";
import "./pipelines.css";

type Props = {
  services: ActiveService[];
  index: MonitoringIndex;
  canEdit: boolean;
  initialTarget?: string;
  initialReading?: string;
  onBack: () => void;
  onStarted: (id: string) => void;
};

export default function PipelineWorkspace({
  services,
  index,
  canEdit,
  initialTarget,
  initialReading,
  onBack,
  onStarted,
}: Props) {
  const { system } = useCatalogue();
  const [params, setParams] = useSearchParams();
  const [catalog, setCatalog] = useState<PipelineCatalog>();
  const [source, setSource] = useState<{ id: string; view?: PipelineServiceView; error?: string }>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const id = params.get("pipeline");
  const creating = params.get("create") === "monitoring";
  const contextReading = !initialTarget || index.targets.find((target) => target.id === initialTarget)
    ?.inputs.some((input) => input.stream.id === initialReading) ? initialReading : undefined;
  const replacementId = params.get("replace");
  const sourceId = replacementId ?? params.get("from");
  const predecessor = source?.id === sourceId ? source.view : undefined;
  const sourceError = source?.id === sourceId ? source.error : undefined;
  const replacement = services.find((service) => service.id === replacementId);
  const collectionReady = collectionApplied(system.snapshot?.runtime);
  useEffect(() => {
    const controller = new AbortController();
    void pipelinesApi.catalog(controller.signal).then(
      (next) => {
        setCatalog(next);
        setError("");
      },
      (reason) => {
        if (!controller.signal.aborted) setError(getErrorMessage(reason));
      },
    );
    return () => controller.abort();
  }, [retry]);
  useEffect(() => {
    if (!sourceId) return;
    const controller = new AbortController();
    void pipelinesApi
      .service(sourceId, controller.signal)
      .then((view) => { if (!controller.signal.aborted) setSource({ id: sourceId, view }); }, (reason) => {
        if (!controller.signal.aborted) setSource({ id: sourceId, error: getErrorMessage(reason) });
      });
    return () => controller.abort();
  }, [sourceId, retry]);
  const open = (pipelineId: string, targetId?: string) => setParams(openPipeline(params, pipelineId, targetId));
  const create = () => setParams(createPipeline(params));
  const library = () => setParams(showLibrary(params));
  if (!catalog)
    return (
      <section aria-label="Pipelines">
        <Breadcrumb steps={[{ label: "Monitoring", onClick: onBack }]} current={creating ? "New service" : "Templates"} />
        {error ? (
          <p role="alert" className="pl-error">
            {error}
            <button onClick={() => setRetry((value) => value + 1)}>
              Retry
            </button>
          </p>
        ) : (
          <p role="status">Opening pipelines…</p>
        )}
      </section>
    );
  if (!id && params.get("view") === "pipelines")
    return (
      <PipelineLibrary
        catalog={catalog}
        canEdit={canEdit}
        onCreate={create}
        onOpen={open}
        onBack={creating ? create : onBack}
        backLabel={creating ? "New service" : "Monitoring"}
      />
    );
  if (!id && sourceId && !predecessor && !sourceError) return <p role="status">Loading service configuration…</p>;
  if (!id) return <>
    {(error || sourceError) && <p role="alert" className="pl-error">{error || sourceError}<button onClick={() => setRetry((value) => value + 1)}>Retry</button></p>}
    <PipelineCreate key={`${initialTarget ?? ""}:${contextReading ?? ""}:${sourceId ?? ""}:${replacementId ? "replace" : "new"}`} catalog={catalog} canEdit={canEdit} targets={index.targets}
    services={services} byStream={index.byStream} collectionReady={collectionReady}
    initialDocument={sourceId ? predecessor && { definition: predecessor.definition, layout: predecessor.layout } : undefined}
    replaceService={replacement} predecessor={sourceId ? predecessor : undefined}
    sourceService={sourceId ? { id: sourceId, replace: !!replacementId } : undefined}
    activationBlocked={sourceId && (!predecessor || replacementId && !replacement) ? "This service configuration is unavailable. Return to Monitoring and choose an available service." : undefined}
    initialTarget={initialTarget} initialReading={contextReading} onStarted={onStarted} onManage={library} onBack={onBack} />
  </>;
  return (
    <>
      {(error || sourceError) && (
        <p role="alert" className="pl-error">
          {error || sourceError}
        </p>
      )}
      {replacementId && !replacement && (
        <p className="pl-warning">
          The requested predecessor is no longer available.{" "}
          <button
            type="button"
            onClick={() => setParams(dropReplacement(params))}
          >
            Choose to start a new service instead
          </button>
        </p>
      )}
      <PipelineEditor
        key={id}
        id={id}
        catalog={catalog}
        canEdit={canEdit}
        targets={index.targets}
        services={services}
        byStream={index.byStream}
        initialTarget={
          initialTarget ??
          (replacement
            ? predecessorEntity(predecessor)
            : undefined)
        }
        initialReading={contextReading}
        collectionReady={collectionReady}
        revisionId={params.get("revision") ?? undefined}
        activationId={params.get("activation") ?? undefined}
        replaceService={replacement}
        sourceService={replacementId ? { id: replacementId, replace: true } : undefined}
        predecessor={predecessor}
        activationBlocked={
          replacementId && !replacement
            ? "Select an available predecessor or explicitly choose a new service before activation."
            : undefined
        }
        onBack={creating ? onBack : library}
        backLabel={creating ? "Monitoring" : "Templates"}
        onManage={library}
        onRevision={(revision) => setParams(setRevision(params, revision))}
        onOperation={(activation) => setParams(setActivation(params, activation))}
        onStarted={onStarted}
      />
    </>
  );
}
