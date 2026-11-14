import { useCallback, useEffect, useState } from "react";
import { Bot, FlaskConical, Play, TriangleAlert, User } from "lucide-react";
import toast from "react-hot-toast";
import { Breadcrumb } from "@/components/Breadcrumb";
import { RelativeTime } from "@/components/RelativeTime";
import { getErrorMessage } from "@/lib/errors";
import type { ActiveService } from "@/types/monitoring";
import type { MonitorCapacity, PipelineProposalSummary } from "@/types/pipelines.generated";
import { pipelinesApi } from "./api";
import { usePipelineApply } from "./applySession";
import { PipelineApplyStatus } from "./PipelineApplyStatus";
import { proposalOutcome } from "./proposals";

/** A note that an open proposal binds readings the catalogue no longer has. */
function missingReadings(proposal: PipelineProposalSummary): string {
  const missing = proposal.missing_readings ?? [];
  if (!missing.length) return "";
  return `${missing.length === 1 ? "Its reading no longer exists" : "Its readings no longer exist"}: ${missing.join(", ")}. It cannot start as proposed.`;
}

/** Decline in place, with an optional note for the author. */
function DeclineProposal({ proposal, onDeclined, named = false }: {
  proposal: PipelineProposalSummary;
  onDeclined: () => void;
  /** In a list, the controls name the proposal they act on. */
  named?: boolean;
}) {
  const of = named ? ` ${proposal.name}` : "";
  const [declining, setDeclining] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const decline = async () => {
    setBusy(true); setError("");
    try {
      await pipelinesApi.decideProposal(proposal.id, { status: "declined", note: note.trim() || null });
      toast.success(`Declined ${proposal.name}.`, { id: "pipeline-proposal" });
      onDeclined();
    } catch (reason) { setError(getErrorMessage(reason)); }
    finally { setBusy(false); }
  };

  return <>
    {error && <p role="alert" className="pl-field-error">{error}</p>}
    {declining
      ? <form className="pl-proposal-decline" onSubmit={(event) => { event.preventDefault(); void decline(); }}>
        <input autoFocus aria-label={`Why you decline${of}`} placeholder="Why, for the author (optional)" maxLength={2000}
          value={note} disabled={busy} onChange={(event) => setNote(event.target.value)} />
        <button type="submit" disabled={busy}>Decline proposal</button>
        <button type="button" disabled={busy} onClick={() => { setDeclining(false); setError(""); }}>Cancel</button>
      </form>
      : <button type="button" aria-label={`Decline${of}`} onClick={() => setDeclining(true)}>Decline</button>}
  </>;
}

/** Why a proposal cannot start from the list, or nothing when it can. */
function startBlocked(proposal: PipelineProposalSummary, full: boolean, replaced?: ActiveService): string {
  if (proposal.missing_readings?.length) return "Its readings are gone. Review it to choose others.";
  if (proposal.replace_monitor_id && !replaced) return "The service it replaces no longer runs. Review it to start it as a new one.";
  if (full && !proposal.replace_monitor_id) return "No monitor place is free.";
  return "";
}

/**
 * Start the proposed design as it was handed in, live or in shadow. An update keeps the service it
 * replaces in shadow or live. Once the start is requested the proposal counts as accepted.
 */
function StartProposal({ proposal, blocked, replaced, onStarted, onChoosing }: {
  proposal: PipelineProposalSummary;
  blocked: string;
  replaced?: ActiveService;
  onStarted?: (id: string) => void;
  onChoosing: (choosing: boolean) => void;
}) {
  const [choosing, setChoosingState] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const completed = useCallback((id: string) => onStarted?.(id), [onStarted]);
  const apply = usePipelineApply(`proposal:${proposal.id}:apply`, completed);
  const setChoosing = (next: boolean) => { setChoosingState(next); onChoosing(next); };
  const reason = `pl-proposal-blocked-${proposal.id}`;
  const update = !!proposal.replace_monitor_id;

  const start = async (shadow: boolean) => {
    setLoading(true); setError("");
    try {
      const full = await pipelinesApi.proposal(proposal.id);
      await apply.session.submit({ definition: full.definition, layout: full.layout, bindings: full.bindings,
        display_name: full.name, idempotency_key: crypto.randomUUID(), replace_monitor_id: full.replace_monitor_id, shadow });
      // Starting the design accepts it; someone who decided it meanwhile keeps the last word.
      if (apply.session.getSnapshot().operationId)
        void pipelinesApi.decideProposal(proposal.id, { status: "accepted" }).catch(() => undefined);
    } catch (reason) { setError(getErrorMessage(reason)); }
    finally { setLoading(false); }
  };

  if (apply.request || apply.operationId || apply.error)
    return <PipelineApplyStatus apply={apply} onReset={() => { apply.session.reset(); setChoosing(false); }} />;
  return <>
    {error && <p role="alert" className="pl-field-error">{error}</p>}
    {choosing
      ? <div className="pl-proposal-start" role="group" aria-label={`Start ${proposal.name}`}>
        {update
          ? <button type="button" className="mn-primary" disabled={loading} onClick={() => void start(!!replaced?.shadow)}>
            <Play size={14} aria-hidden="true" />{`Update ${replaced?.display_name || "the service"}`}</button>
          : <>
            <button type="button" className="mn-primary" disabled={loading} onClick={() => void start(false)}>
              <Play size={14} aria-hidden="true" />Start monitoring</button>
            <button type="button" disabled={loading} onClick={() => void start(true)}>Start in shadow</button>
          </>}
        <button type="button" disabled={loading} onClick={() => { setChoosing(false); setError(""); }}>Cancel</button>
      </div>
      : <button type="button" className="mn-primary" aria-label={`${update ? "Update with" : "Start"} ${proposal.name}`}
        disabled={!!blocked} aria-describedby={blocked ? reason : undefined} onClick={() => setChoosing(true)}>
        <Play size={14} aria-hidden="true" />{update ? "Update" : "Start"}</button>}
    {blocked && !choosing && <small id={reason} className="pl-proposal-why">{blocked}</small>}
  </>;
}

/** One proposal: what it is and why, who handed it in, and what a member may do with it. */
function ProposalRow({ proposal, canDecide, full, replaced, onReview, onDeclined, onStarted }: {
  proposal: PipelineProposalSummary;
  canDecide: boolean;
  full: boolean;
  replaced?: ActiveService;
  onReview: () => void;
  onDeclined: () => void;
  onStarted?: (id: string) => void;
}) {
  const [starting, setStarting] = useState(false);
  const missing = missingReadings(proposal);
  const open = proposal.status === "open";
  const outcome = proposalOutcome(proposal);
  const tone = proposal.status === "accepted" ? "positive" : proposal.status === "declined" ? "danger" : "neutral";
  return <li className="pl-proposal-row">
    <button type="button" className="pl-proposal-body" onClick={onReview} aria-label={`Review ${proposal.name}`}>
      <span className="pl-proposal-title">
        <strong>{proposal.name}</strong>
        <span className="pl-proposal-tag">{proposal.author_kind === "agent" ? <Bot size={13} aria-hidden="true" /> : <User size={13} aria-hidden="true" />}
          {proposal.author_kind === "agent" ? "Agent" : "Member"}</span>
        {proposal.test_run_id && <span className="pl-proposal-tag"><FlaskConical size={13} aria-hidden="true" />Tested</span>}
        {proposal.replace_monitor_id && <span className="pl-proposal-tag">Update</span>}
      </span>
      <span className="pl-proposal-reason">{proposal.reason}</span>
      <small>Proposed by {proposal.author} <RelativeTime value={proposal.created_at} />
        {proposal.replace_monitor_id && ` · Replaces ${replaced?.display_name || "a running service"}`}</small>
      {!open && <small className={`mn-state mn-state--${tone}`}>{outcome}</small>}
      {missing && <small className="pl-proposal-missing"><TriangleAlert size={13} aria-hidden="true" />{missing}</small>}
    </button>
    {open && canDecide && <div className="pl-proposal-actions">
      <StartProposal proposal={proposal} blocked={startBlocked(proposal, full, replaced)} replaced={replaced}
        onStarted={onStarted} onChoosing={setStarting} />
      {!starting && <DeclineProposal proposal={proposal} named onDeclined={onDeclined} />}
    </div>}
  </li>;
}

/**
 * The designs handed in for a decision. A member who manages monitors starts or declines one here,
 * or reviews it in the setup first.
 */
export function PipelineProposalList({ onReview, onBack, onStarted, canDecide = false, services = [] }: {
  onReview: (proposal: PipelineProposalSummary) => void;
  onBack: () => void;
  onStarted?: (id: string) => void;
  canDecide?: boolean;
  /** The running services, so an update names the one it replaces. */
  services?: ActiveService[];
}) {
  const [decided, setDecided] = useState(false);
  const [result, setResult] = useState<{ decided: boolean; items: PipelineProposalSummary[] }>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const items = result?.decided === decided ? result.items : undefined;
  const [capacity, setCapacity] = useState<MonitorCapacity>();
  const [waiting, setWaiting] = useState<number>();

  useEffect(() => {
    const controller = new AbortController();
    // The room to start is a hint beside the list; without it the list still works.
    void pipelinesApi.capacity(controller.signal).then(
      (next) => { if (!controller.signal.aborted) setCapacity(next); },
      () => undefined,
    );
    return () => controller.abort();
  }, [retry]);
  const full = capacity !== undefined && capacity.running >= capacity.limit;
  const free = capacity ? Math.max(0, capacity.limit - capacity.running) : 0;

  useEffect(() => {
    const controller = new AbortController();
    void pipelinesApi.proposals(decided ? undefined : "open", controller.signal).then(
      (next) => {
        if (controller.signal.aborted) return;
        setResult({ decided, items: next }); setError("");
        if (!decided) setWaiting(next.length);
      },
      (reason) => { if (!controller.signal.aborted) setError(getErrorMessage(reason)); },
    );
    return () => controller.abort();
  }, [decided, retry]);
  const filters = [{ id: false, label: "Waiting", count: waiting }, { id: true, label: "All" }];

  return <section className="pl-library pl-proposals" aria-label="Proposals">
    <Breadcrumb steps={[{ label: "Monitoring", onClick: onBack }]} current="Proposals" />
    <div className="ex-workspace-heading pl-proposals-heading">
      <h1>Proposals</h1>
      {capacity && <div className={`pl-capacity${full ? " is-full" : ""}`} role={full ? "alert" : undefined}
        title={full ? undefined : `${capacity.running} running`}>
        <span className="pl-capacity-meter" aria-hidden="true">
          {Array.from({ length: Math.min(capacity.limit, 12) }, (_, index) =>
            <i key={index} className={index < Math.min(capacity.running, 12) ? "is-taken" : undefined} />)}
        </span>
        <span>{full
          ? `All ${capacity.limit} monitor places are taken.`
          : `${free} of ${capacity.limit} monitor places are free.`}</span>
      </div>}
    </div>
    <p className="pl-proposals-intro">Designs an agent or a member handed in for a decision. Start one as proposed, review it in the setup first, or decline it.
      {full && " Starting a proposal needs a free place: stop a monitor first, or start one that replaces a running service."}</p>
    <div className="mn-list-tools pl-proposals-tools">
      <div className="mn-filters" aria-label="Filter proposals">
        {filters.map((item) => <button key={item.label} type="button" aria-pressed={decided === item.id} onClick={() => setDecided(item.id)}>
          {item.label}{item.count !== undefined && <> <span className="mn-filter-count">{item.count}</span></>}
        </button>)}
      </div>
    </div>
    {error && <p role="alert" className="pl-error">{error}
      <button type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button>
    </p>}
    {!items ? !error && <p className="mn-loading" role="status">Loading proposals…</p> : !items.length
      ? <div className="mn-empty"><h2>{decided ? "No proposals yet" : "Nothing to decide"}</h2>
        <p>{decided ? "Proposals appear here when an agent or a member hands in a design."
          : "No proposal waits for a decision."}</p></div>
      : <ul className="pl-proposal-rows">
        {items.map((proposal) => <ProposalRow key={proposal.id} proposal={proposal} canDecide={canDecide} full={full}
          replaced={services.find((service) => service.id === proposal.replace_monitor_id)}
          onReview={() => onReview(proposal)} onStarted={onStarted} onDeclined={() => setRetry((value) => value + 1)} />)}
      </ul>}
  </section>;
}

/**
 * Who proposed the design on the canvas and why, above the setup. A member who may start services
 * declines it here; starting the service accepts it.
 */
export function PipelineProposalNotice({ proposal, canDecide, onDeclined }: {
  proposal: PipelineProposalSummary;
  canDecide: boolean;
  onDeclined: () => void;
}) {
  const open = proposal.status === "open";
  const missing = missingReadings(proposal);

  return <div className="pl-proposal" role="group" aria-label={`Proposal by ${proposal.author}`}>
    <div className="pl-proposal-text">
      <p><strong>Proposed by {proposal.author}</strong> <RelativeTime value={proposal.created_at} /></p>
      <p>{proposal.reason}</p>
      {missing && <p className="pl-proposal-missing">{missing}</p>}
      <p className="pl-proposal-state">{open ? canDecide ? "Starting the service accepts the proposal." : "It waits for a member who manages monitors."
        : `${proposalOutcome(proposal)}.`}</p>
    </div>
    {open && canDecide && <DeclineProposal proposal={proposal} onDeclined={onDeclined} />}
  </div>;
}
