import { useEffect, useState } from "react";
import { getErrorMessage } from "@/lib/errors";
import { pipelinesApi } from "./api";
import type { PipelineRevisionView, PipelineView } from "./contracts";
import { PipelineCreate, type PipelineSetupProps } from "./PipelineCreate";
import { PipelineActivation } from "./PipelineActivation";

type Props = Omit<PipelineSetupProps, "initialDesign" | "initialDocument"> & {
  id: string; revisionId?: string; activationId?: string;
  onRevision: (id?: string) => void; onOperation: (id: string) => void;
};

export default function PipelineEditor(props: Props) {
  const [pipeline, setPipeline] = useState<PipelineView>();
  const [revision, setRevision] = useState<PipelineRevisionView>();
  const [loadedRevision, setLoadedRevision] = useState<string>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([pipelinesApi.get(props.id, controller.signal),
      props.revisionId ? pipelinesApi.revision(props.id, props.revisionId, controller.signal) : undefined,
    ]).then(([design, version]) => {
      if (controller.signal.aborted) return;
      setPipeline(design); setRevision(version); setLoadedRevision(props.revisionId); setError("");
    }, (reason) => { if (!controller.signal.aborted) setError(getErrorMessage(reason)); });
    return () => controller.abort();
  }, [props.id, props.revisionId, retry]);
  if (!pipeline || pipeline.id !== props.id || loadedRevision !== props.revisionId) return <section aria-label="Pipeline editor">
    <button className="mn-back" onClick={props.onBack}>Back</button>
    {error ? <p className="pl-error" role="alert">{error}<button onClick={() => setRetry((value) => value + 1)}>Retry</button></p>
      : <p role="status">Loading template…</p>}
  </section>;
  // Recover existing links to an in-flight start created by earlier releases.
  if (props.activationId && revision) return <PipelineActivation revision={revision} previous={props.predecessor?.definition}
    previousBindings={Object.fromEntries((props.predecessor?.run?.execution?.bindings ?? []).map((binding) => [binding.slot_id, binding.reading_id]))}
    replaceService={props.replaceService} targets={props.targets} services={props.services} byStream={props.byStream}
    initialTarget={props.initialTarget} initialReading={props.initialReading} defaultName={pipeline.name}
    collectionReady={props.collectionReady} operationId={props.activationId} onOperation={props.onOperation}
    onComplete={props.onStarted} onClose={() => props.onRevision(undefined)} />;
  return <>
    <PipelineCreate key={pipeline.id} {...props} initialDesign={pipeline}
      initialDocument={revision ? { definition: revision.definition, layout: pipeline.layout } : undefined} />
    {props.canEdit && props.catalog.authoring_enabled && <details className="pl-archive">
      <summary>Template options</summary>
      <p>{pipeline.archived ? "Restore this template to use it again." : "Archiving removes the template from the active library. Running services and history are kept."}</p>
      {error && <p className="pl-error" role="alert">{error}</p>}
      <button type="button" onClick={async () => {
        try {
          const current = await pipelinesApi.get(pipeline.id);
          await pipelinesApi.metadata(pipeline.id, { expected_version: current.version,
            name: current.name, description: current.description, archived: !current.archived });
          props.onManage();
        } catch (reason) { setError(getErrorMessage(reason)); }
      }}>{pipeline.archived ? "Restore template" : "Archive template"}</button>
    </details>}
  </>;
}
