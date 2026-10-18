import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getErrorMessage } from "@/lib/errors";
import type { ActiveService } from "@/types/monitoring";
import type { MonitoringIndex } from "../monitoring/serviceModel";
import { useCatalogue } from "../workspace/catalogue-context";
import { pipelinesApi } from "./api";
import type { PipelineCatalog, PipelineServiceView } from "./contracts";
import { PipelineLibrary } from "./PipelineLibrary";
import { PipelineCreate } from "./PipelineCreate";
import PipelineEditor from "./PipelineEditor";
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
  const [predecessor, setPredecessor] = useState<PipelineServiceView>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const id = params.get("pipeline");
  const creating = params.get("create") === "monitoring";
  const contextReading = !initialTarget || index.targets.find((target) => target.id === initialTarget)
    ?.inputs.some((input) => input.stream.id === initialReading) ? initialReading : undefined;
  const replacementId = params.get("replace");
  const replacement = services.find((service) => service.id === replacementId);
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
    if (!replacementId) return;
    const controller = new AbortController();
    void pipelinesApi
      .service(replacementId, controller.signal)
      .then(setPredecessor, (reason) => {
        if (!controller.signal.aborted) setError(getErrorMessage(reason));
      });
    return () => controller.abort();
  }, [replacementId]);
  const open = (pipelineId: string, targetId?: string) => {
    const next = new URLSearchParams(params);
    next.set("pipeline", pipelineId);
    if (params.get("view") === "pipelines") next.delete("create");
    if (targetId) next.set("target", targetId);
    next.delete("revision");
    next.delete("activation");
    next.delete("view");
    setParams(next);
  };
  const create = () => {
    const next = new URLSearchParams(params);
    ["pipeline", "revision", "activation", "view", "replace"].forEach((key) => next.delete(key));
    next.set("create", "monitoring");
    setParams(next);
  };
  const library = () => {
    const next = new URLSearchParams(params);
    ["pipeline", "revision", "activation", "replace"].forEach((key) =>
      next.delete(key),
    );
    next.set("view", "pipelines");
    setParams(next);
  };
  if (!catalog)
    return (
      <section aria-label="Pipelines">
        <button className="mn-back" onClick={onBack}>
          Monitoring
        </button>
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
      />
    );
  if (!id) return <PipelineCreate key={`${initialTarget ?? ""}:${contextReading ?? ""}`} catalog={catalog} canEdit={canEdit} targets={index.targets}
    initialTarget={initialTarget} initialReading={contextReading} onCreated={open}
    onManage={library} onBack={onBack} />;
  return (
    <>
      {error && (
        <p role="alert" className="pl-error">
          {error}
        </p>
      )}
      {replacementId && !replacement && (
        <p className="pl-warning">
          The requested predecessor is no longer available.{" "}
          <button
            type="button"
            onClick={() => {
              const next = new URLSearchParams(params);
              next.delete("replace");
              setParams(next);
            }}
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
            ? predecessor?.run?.execution?.bindings[0]?.entity_id
            : undefined)
        }
        initialReading={contextReading}
        collectionReady={
          system.snapshot?.runtime.collection?.status === "applied"
        }
        revisionId={params.get("revision") ?? undefined}
        activationId={params.get("activation") ?? undefined}
        replaceService={replacement}
        predecessor={predecessor}
        activationBlocked={
          replacementId && !replacement
            ? "Select an available predecessor or explicitly choose a new service before activation."
            : undefined
        }
        onBack={creating ? onBack : library}
        backLabel={creating ? "Monitoring" : "Saved designs"}
        onOpen={open}
        onRevision={(revision) => {
          const next = new URLSearchParams(params);
          if (revision) next.set("revision", revision);
          else next.delete("revision");
          next.delete("activation");
          setParams(next);
        }}
        onOperation={(activation) => {
          const next = new URLSearchParams(params);
          next.set("activation", activation);
          setParams(next);
        }}
        onStarted={onStarted}
      />
    </>
  );
}
