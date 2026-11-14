import { useEffect, useMemo, useState } from "react";
import { Breadcrumb } from "@/components/Breadcrumb";
import { useSearchParams } from "react-router-dom";
import { getErrorMessage } from "@/lib/errors";
import type { ActiveService } from "@/types/monitoring";
import type { MonitoringIndex } from "@/domain/monitoring/serviceModel";
import { useCatalogue } from "../workspace/catalogue-context";
import { collectionApplied } from "@/domain/system/collectionRules";
import { predecessorSource } from "./bindings";
import { pipelinesApi } from "./api";
import type { PipelineCatalog, PipelineProposal, PipelineServiceView } from "./contracts";
import { PipelineLibrary } from "./PipelineLibrary";
import { PipelineCreate } from "./PipelineCreate";
import PipelineEditor from "./PipelineEditor";
import { PipelineProposalList, PipelineProposalNotice } from "./PipelineProposals";
import { createPipeline, dropReplacement, openPipeline, reviewProposal, setRevision, showLibrary, showProposals, suggestedBindings } from "@/domain/monitoring/monitoringView";
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
  const [opened, setOpened] = useState<{ id: string; proposal?: PipelineProposal; error?: string }>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const id = params.get("pipeline");
  const suggested = useMemo(() => suggestedBindings(params), [params]);
  const creating = params.get("create") === "monitoring";
  const contextReading = !initialTarget || index.targets.find((target) => target.id === initialTarget)
    ?.inputs.some((input) => input.stream.id === initialReading) ? initialReading : undefined;
  const replacementId = params.get("replace");
  const sourceId = replacementId ?? params.get("from");
  const predecessor = source?.id === sourceId ? source.view : undefined;
  const sourceError = source?.id === sourceId ? source.error : undefined;
  const replacement = services.find((service) => service.id === replacementId);
  const proposalId = params.get("proposal");
  const proposal = opened?.id === proposalId ? opened.proposal : undefined;
  const proposalError = opened?.id === proposalId ? opened.error : undefined;
  // The test a design was proposed with is shown beside it, as the reason to believe the proposal.
  const tested = useMemo(() => proposal?.test_run_id
    ? { run: proposal.test_run_id, by: proposal.author, definition: proposal.definition } : undefined, [proposal]);
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
  useEffect(() => {
    if (!proposalId) return;
    const controller = new AbortController();
    void pipelinesApi.proposal(proposalId, controller.signal).then(
      (proposal) => { if (!controller.signal.aborted) setOpened({ id: proposalId, proposal }); },
      (reason) => { if (!controller.signal.aborted) setOpened({ id: proposalId, error: getErrorMessage(reason) }); },
    );
    return () => controller.abort();
  }, [proposalId, retry]);
  const proposals = () => setParams(showProposals(params));
  /** The member started the proposed design. Someone who decided it meanwhile has the last word. */
  const accept = (id: string) => void pipelinesApi.decideProposal(id, { status: "accepted" })
    .then(({ status, decided_by, decided_at, decision_note }) => setOpened((current) => current?.proposal?.id === id
      ? { id, proposal: { ...current.proposal, status, decided_by, decided_at, decision_note } } : current), () => undefined);
  const open = (pipelineId: string, targetId?: string) => setParams(openPipeline(params, pipelineId, targetId));
  const create = () => setParams(createPipeline(params));
  const library = () => setParams(showLibrary(params));
  if (!catalog)
    return (
      <section aria-label="Pipelines">
        <Breadcrumb steps={[{ label: "Monitoring", onClick: onBack }]}
          current={params.get("view") === "proposals" ? "Proposals" : creating ? "New service" : "Templates"} />
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
  if (!id && params.get("view") === "proposals")
    return <PipelineProposalList onBack={onBack} canDecide={canEdit} services={services} onStarted={onStarted}
      onReview={(item) => setParams(reviewProposal(params, item.id, item.replace_monitor_id))} />;
  if (!id && sourceId && !predecessor && !sourceError) return <p role="status">Loading service configuration…</p>;
  if (!id && proposalId && !proposal && !proposalError) return <p role="status">Opening proposal…</p>;
  if (!id) return <>
    {(error || sourceError || proposalError) && <p role="alert" className="pl-error">{error || sourceError || proposalError}<button onClick={() => setRetry((value) => value + 1)}>Retry</button></p>}
    <PipelineCreate key={`${initialTarget ?? ""}:${contextReading ?? ""}:${sourceId ?? ""}:${replacementId ? "replace" : "new"}:${proposal?.id ?? ""}`} catalog={catalog} canEdit={canEdit} targets={index.targets}
    services={services} byStream={index.byStream} collectionReady={collectionReady}
    initialDocument={proposal ? { definition: proposal.definition, layout: proposal.layout }
      : sourceId ? predecessor && { definition: predecessor.definition, layout: predecessor.layout } : undefined}
    initialBindings={proposal?.bindings} initialName={proposal?.name} origin={proposal && `proposal:${proposal.id}`}
    notice={proposal && <PipelineProposalNotice proposal={proposal} canDecide={canEdit} onDeclined={proposals} />}
    tested={tested}
    onRequested={proposal?.status === "open" ? () => accept(proposal.id) : undefined}
    replaceService={replacement} predecessor={sourceId ? predecessor : undefined}
    sourceService={sourceId ? { id: sourceId, replace: !!replacementId } : undefined}
    activationBlocked={sourceId && (!predecessor || replacementId && !replacement) ? "This service configuration is unavailable. Return to Monitoring and choose an available service." : undefined}
    initialTarget={initialTarget} initialReading={contextReading} onStarted={onStarted} onManage={library}
    onBack={proposal ? proposals : onBack} backLabel={proposal ? "Proposals" : undefined} />
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
            ? predecessorSource(predecessor)
            : undefined)
        }
        initialReading={contextReading}
        initialBindings={suggested}
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
        onStarted={onStarted}
      />
    </>
  );
}
