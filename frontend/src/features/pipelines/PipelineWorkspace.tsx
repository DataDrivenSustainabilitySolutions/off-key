import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getErrorMessage } from "@/lib/errors";
import type { ActiveService } from "@/types/monitoring";
import type { MonitoringIndex } from "../monitoring/serviceModel";
import { useCatalogue } from "../workspace/catalogue-context";
import { pipelinesApi } from "./api";
import type { PipelineCatalog, PipelineServiceView } from "./contracts";
import { PipelineLibrary } from "./PipelineLibrary";
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
  const open = (pipelineId: string) => {
    const next = new URLSearchParams(params);
    next.set("pipeline", pipelineId);
    next.delete("create");
    next.delete("revision");
    next.delete("activation");
    next.delete("view");
    setParams(next);
  };
  const library = () => {
    const next = new URLSearchParams(params);
    ["pipeline", "revision", "activation", "create", "replace"].forEach((key) =>
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
  if (!id)
    return (
      <PipelineLibrary
        catalog={catalog}
        canEdit={canEdit}
        creating={params.get("create") === "monitoring"}
        targets={index.targets}
        initialTarget={initialTarget}
        initialReading={initialReading}
        onOpen={open}
        onBack={onBack}
      />
    );
  return (
    <>
      <p className="pl-help">
        Shared pipeline library · designs are reusable across sources.
      </p>
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
        initialReading={initialReading}
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
        onBack={library}
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
