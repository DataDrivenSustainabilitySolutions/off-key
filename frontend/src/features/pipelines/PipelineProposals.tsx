import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import * as Popover from "@radix-ui/react-popover";
import { ChevronDown, FlaskConical, Play, TriangleAlert } from "lucide-react";
import toast from "react-hot-toast";
import { Link } from "react-router-dom";
import { Breadcrumb } from "@/components/Breadcrumb";
import { RelativeTime } from "@/components/RelativeTime";
import { getErrorMessage } from "@/lib/errors";
import type { ActiveService } from "@/types/monitoring";
import type { MonitorCapacity, PipelineProposalSummary } from "@/types/pipelines.generated";
import { pipelinesApi } from "./api";
import { usePipelineApply } from "./applySession";
import { PipelineApplyStatus } from "./PipelineApplyStatus";
import { proposalOutcome, proposalTone, testRunHref } from "./proposals";
import { AuthorChip, RationaleFields } from "../workspace/RationaleCard";

/** A note that an open proposal binds readings the catalogue no longer has. */
function missingReadings(proposal: PipelineProposalSummary): string {
  const missing = proposal.missing_readings ?? [];
  if (!missing.length) return "";
  return `${missing.length === 1 ? "Its reading no longer exists" : "Its readings no longer exist"}: ${missing.join(", ")}. It cannot start as proposed.`;
}

/** Whether the design becomes a service of its own or takes the place of one that runs. */
const proposedAs = (proposal: PipelineProposalSummary, replaced?: ActiveService) => proposal.replace_monitor_id
  ? `Replaces ${replaced?.display_name || "a running service"}` : "New service";

/** Who a proposal is by, in words: a member by name, an agent as an agent, since its key's name says little to a reviewer. */
const proposedBy = (proposal: PipelineProposalSummary) => proposal.author_kind === "agent" ? "an agent" : proposal.author;

/** Who handed the design in and when, what starting it does, and whether it came with a test. */
function ProposalByline({ proposal, replaced }: { proposal: PipelineProposalSummary; replaced?: ActiveService }) {
  return <ul className="pl-proposal-meta">
    <li><AuthorChip author={proposal.author} kind={proposal.author_kind} named={false} /><RelativeTime value={proposal.created_at} /></li>
    <li>{proposedAs(proposal, replaced)}</li>
    {proposal.test_run_id
      ? <li className="pl-proposal-tested"><FlaskConical size={13} aria-hidden="true" />Tested on history</li>
      : <li>Not tested</li>}
  </ul>;
}

/**
 * Where a proposal stands: waiting, or who decided it, when, and the word they left for the author.
 * What follows from that for the reader, such as what a decision takes, reads under it.
 */
function ProposalDecision({ proposal, children }: { proposal: PipelineProposalSummary; children?: ReactNode }) {
  return <div className="pl-proposal-decision">
    <p><span className={`mn-state mn-state--${proposalTone(proposal)}`}>{proposalOutcome(proposal) || "Waiting for a decision"}</span>
      {proposal.decided_at && <> <RelativeTime value={proposal.decided_at} /></>}</p>
    {proposal.decision_note && <blockquote>{proposal.decision_note}</blockquote>}
    {children}
  </div>;
}

/**
 * Decline from a small dialog at the button, with an optional note for the author. In a list the
 * button names the proposal it acts on.
 */
export function DeclineProposal({ proposal, onDeclined, named = false }: {
  proposal: PipelineProposalSummary;
  onDeclined: () => void;
  named?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const field = useId();

  const decline = async () => {
    setBusy(true); setError("");
    try {
      await pipelinesApi.decideProposal(proposal.id, { status: "declined", note: note.trim() || null });
      toast.success(`Declined ${proposal.name}.`, { id: "pipeline-proposal" });
      setOpen(false);
      onDeclined();
    } catch (reason) { setError(getErrorMessage(reason)); }
    finally { setBusy(false); }
  };

  return <Popover.Root open={open} onOpenChange={(next) => { if (busy) return; setOpen(next); setError(""); }}>
    <Popover.Trigger className="pl-decline" aria-label={named ? `Decline ${proposal.name}` : undefined}>Decline</Popover.Trigger>
    <Popover.Portal><Popover.Content className="pl-library pl-decision" align="end" sideOffset={8} collisionPadding={12}
      aria-label={`Decline ${proposal.name}`}>
      <form onSubmit={(event) => { event.preventDefault(); void decline(); }}>
        <h3>Decline this proposal</h3>
        <label className="pl-field" htmlFor={field}><span>Note for the author (optional)</span>
          <textarea id={field} rows={3} maxLength={2000} placeholder="What would make it acceptable?"
            value={note} disabled={busy} onChange={(event) => setNote(event.target.value)} />
        </label>
        <p className="pl-help">The proposal leaves the waiting list. Its author can read the note.</p>
        {error && <p role="alert" className="pl-field-error">{error}</p>}
        <div className="pl-decision-actions">
          <button type="button" disabled={busy} onClick={() => { setOpen(false); setError(""); }}>Cancel</button>
          <button type="submit" className="pl-decision-decline" disabled={busy}>Decline proposal</button>
        </div>
      </form>
    </Popover.Content></Popover.Portal>
  </Popover.Root>;
}

/** Why a proposal cannot start from the list, or nothing when it can. */
function startBlocked(proposal: PipelineProposalSummary, full: boolean, replaced?: ActiveService): string {
  if (proposal.missing_readings?.length) return "Review it to choose other readings.";
  if (proposal.replace_monitor_id && !replaced) return "The service it replaces no longer runs. Review it to start it as a new one.";
  if (full && !proposal.replace_monitor_id) return "No monitor place is free.";
  return "";
}

/** One way to start, as a row to press: its name, and under it what it does. */
function StartChoice({ name, disabled, onChoose, children }: { name: string; disabled: boolean; onChoose: () => void; children: ReactNode }) {
  const label = useId();
  const detail = useId();
  return <li><button type="button" disabled={disabled} aria-labelledby={label} aria-describedby={detail} onClick={onChoose}>
    <strong id={label}><Play size={14} aria-hidden="true" />{name}</strong>
    <small id={detail}>{children}</small>
  </button></li>;
}

/**
 * Start the proposed design as it was handed in, live or in shadow, from a small dialog at the
 * button that says what each choice does. An update keeps the service it replaces in shadow or live.
 */
function StartProposal({ proposal, blocked, describedBy, replaced, apply }: {
  proposal: PipelineProposalSummary;
  blocked: string;
  /** Names the line that says why it cannot start. */
  describedBy: string;
  replaced?: ActiveService;
  apply: ReturnType<typeof usePipelineApply>;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const update = !!proposal.replace_monitor_id;
  const label = `${update ? "Update with" : "Start"} ${proposal.name}`;

  const start = async (inShadow: boolean) => {
    setLoading(true); setError("");
    try {
      const full = await pipelinesApi.proposal(proposal.id);
      await apply.session.submit({ definition: full.definition, layout: full.layout, bindings: full.bindings,
        display_name: full.name, idempotency_key: crypto.randomUUID(), replace_monitor_id: full.replace_monitor_id, shadow: inShadow,
        proposal_id: proposal.id });
    } catch (reason) { setError(getErrorMessage(reason)); }
    finally { setLoading(false); }
  };

  return <Popover.Root open={open} onOpenChange={(next) => { if (loading) return; setOpen(next); setError(""); }}>
    <Popover.Trigger aria-label={label} disabled={!!blocked} aria-describedby={blocked ? describedBy : undefined}>
      <Play size={14} aria-hidden="true" />{update ? "Update" : "Start"}
    </Popover.Trigger>
    <Popover.Portal><Popover.Content className="pl-library pl-decision" align="start" sideOffset={8} collisionPadding={12} aria-label={label}>
      <h3>{update ? "Update as proposed" : "Start as proposed"}</h3>
      <ul className="pl-decision-choices">
        {update
          ? <StartChoice name={`Update ${replaced?.display_name || "the service"}`} disabled={loading} onChoose={() => void start(!!replaced?.shadow)}>
            Replaces the design that runs{replaced?.shadow ? " and stays in shadow" : ""}. Monitoring pauses briefly and learning
            restarts. History is kept.</StartChoice>
          : <>
            <StartChoice name="Start monitoring" disabled={loading} onChoose={() => void start(false)}>Raises its alarms.</StartChoice>
            <StartChoice name="Start in shadow" disabled={loading} onChoose={() => void start(true)}>
              Records the alarms it would raise and raises none.</StartChoice>
          </>}
      </ul>
      {error && <p role="alert" className="pl-field-error">{error}</p>}
      <div className="pl-decision-actions">
        <small>{update ? "Updating" : "Starting"} it accepts the proposal.</small>
        <button type="button" disabled={loading} onClick={() => { setOpen(false); setError(""); }}>Cancel</button>
      </div>
    </Popover.Content></Popover.Portal>
  </Popover.Root>;
}

/**
 * What a member who manages monitors does with a waiting proposal from the list: start it as it was
 * handed in, or decline it. While a start is under way its progress stands in their place. Once the
 * start is requested the proposal counts as accepted.
 */
function ProposalActions({ proposal, full, replaced, onDeclined, onStarted }: {
  proposal: PipelineProposalSummary;
  full: boolean;
  replaced?: ActiveService;
  onDeclined: () => void;
  onStarted?: (id: string) => void;
}) {
  const completed = useCallback((id: string) => onStarted?.(id), [onStarted]);
  const apply = usePipelineApply(`proposal:${proposal.id}:apply`, completed);
  const reason = useId();

  // Starting the design accepts it, also when an interrupted request is recovered. Someone who
  // decided it meanwhile keeps the last word.
  const accepted = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!apply.operationId || accepted.current === apply.operationId) return;
    accepted.current = apply.operationId;
    void pipelinesApi.decideProposal(proposal.id, { status: "accepted" }).catch(() => undefined);
  }, [apply.operationId, proposal.id]);

  if (apply.request || apply.operationId) return <PipelineApplyStatus apply={apply} />;
  const blocked = startBlocked(proposal, full, replaced);
  return <>
    <StartProposal proposal={proposal} blocked={blocked} describedBy={reason} replaced={replaced} apply={apply} />
    <DeclineProposal proposal={proposal} named onDeclined={onDeclined} />
    {blocked && <small id={reason} className="pl-proposal-hint">{blocked}</small>}
    {/* A refused start leaves no request behind; the actions stay, with the reason, to try again. */}
    {apply.error && <p role="alert" className="pl-field-error">{apply.error}</p>}
  </>;
}

/**
 * One proposal, laid out the same for all of them: its name, who handed it in and as what, then what
 * it watches, the evidence and the limits under their names, and at the bottom what a member may do.
 */
function ProposalCard({ proposal, canDecide, stated, full, replaced, onReview, onDeclined, onStarted }: {
  proposal: PipelineProposalSummary;
  canDecide: boolean;
  /** Among decided proposals every card says where it stands; a list of waiting ones need not. */
  stated: boolean;
  full: boolean;
  replaced?: ActiveService;
  onReview: () => void;
  onDeclined: () => void;
  onStarted?: (id: string) => void;
}) {
  const title = useId();
  const missing = missingReadings(proposal);
  const open = proposal.status === "open";
  // A phone shows what the design watches and keeps the evidence and the limits one press away.
  const [more, setMore] = useState(false);
  return <li className="pl-proposal-card">
    <article aria-labelledby={title} data-more={proposal.rationale ? more : undefined}>
      {/* The name opens the proposal for the pointer; the keyboard has the button below for it. */}
      <h2 id={title}><button type="button" tabIndex={-1} onClick={onReview}>{proposal.name}</button></h2>
      <ProposalByline proposal={proposal} replaced={replaced} />
      {(stated || !open) && <ProposalDecision proposal={proposal} />}
      {proposal.rationale
        ? <>
          <RationaleFields rationale={proposal.rationale} only={["watches", "evidence", "limits"]} />
          <button type="button" className="pl-proposal-more" aria-expanded={more} onClick={() => setMore(!more)}>
            <ChevronDown size={14} aria-hidden="true" />Evidence and limits</button>
        </>
        : <dl className="rationale-fields"><div><dt>Reason</dt><dd className="pl-proposal-reason">{proposal.reason}</dd></div></dl>}
      {missing && <p className="pl-proposal-missing"><TriangleAlert size={14} aria-hidden="true" />{missing}</p>}
      <footer className="pl-proposal-actions">
        {open
          ? <button type="button" className="mn-primary" aria-label={`Review ${proposal.name}`} onClick={onReview}>Review</button>
          : <button type="button" aria-label={`View design of ${proposal.name}`} onClick={onReview}>View design</button>}
        {open && (canDecide
          ? <ProposalActions proposal={proposal} full={full} replaced={replaced} onDeclined={onDeclined} onStarted={onStarted} />
          : <small className="pl-proposal-hint">It waits for a member who manages monitors.</small>)}
      </footer>
    </article>
  </li>;
}

/**
 * The designs handed in for a decision. A member who manages monitors reviews one in the setup, or
 * starts or declines it here.
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
    <p className="pl-proposals-intro"><span className="pl-proposals-about">Designs an agent or a member handed in for a decision.
      {canDecide ? " Review one in the setup, start it as proposed, or decline it." : " Review one in the setup."}</span>
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
      : <ul className="pl-proposal-cards">
        {items.map((proposal) => <ProposalCard key={proposal.id} proposal={proposal} canDecide={canDecide} stated={decided} full={full}
          replaced={services.find((service) => service.id === proposal.replace_monitor_id)}
          onReview={() => onReview(proposal)} onStarted={onStarted} onDeclined={() => setRetry((value) => value + 1)} />)}
      </ul>}
  </section>;
}

/** Said above the canvas while the proposal's design is open: what keeps it from starting as it was handed in. */
export function PipelineProposalWarning({ proposal }: { proposal: PipelineProposalSummary }) {
  const missing = missingReadings(proposal);
  return missing ? <p className="pl-warning" role="status">{missing} Choose other readings at the Input step.</p> : null;
}

/**
 * The proposal beside its design, for the member who decides: where it stands, who handed it in and
 * as what, the way to the test it came with, the rationale under its four names, and what else the
 * author wrote. The decision itself is made with the setup's own Start and the Decline beside it.
 */
export function PipelineProposalBrief({ proposal, canDecide, replaced, onOpenTest }: {
  proposal: PipelineProposalSummary;
  canDecide: boolean;
  replaced?: ActiveService;
  /** Opens the test beside the design, where the setup has one: for members who may use the Dojo. */
  onOpenTest?: () => void;
}) {
  const open = proposal.status === "open";
  const rationale = proposal.rationale;
  // The reason is the whole case of a proposal without a rationale; with one, it is what the author added.
  const note = rationale && proposal.reason === rationale.watches ? "" : proposal.reason;

  return <div className="pl-brief" role="group" aria-label={`Proposal by ${proposedBy(proposal)}`}>
    {/* On a phone the brief is a page of its own and opens with the name the design was handed in under. */}
    <p className="pl-brief-name">{proposal.name}</p>
    <ProposalDecision proposal={proposal}>
      {open && <p className="pl-help">{canDecide
        ? `${proposal.replace_monitor_id ? "Updating" : "Starting"} the service accepts the proposal. Change the design first if you wish.`
        : "It waits for a member who manages monitors."}</p>}
    </ProposalDecision>
    <ProposalByline proposal={proposal} replaced={replaced} />
    {/* The setup has a test only for members who may use the Dojo, so the way to its runs is theirs too. */}
    {onOpenTest && <div className="pl-brief-test">
      <button type="button" onClick={onOpenTest}>
        <FlaskConical size={14} aria-hidden="true" />{proposal.test_run_id ? "Open the test" : "Test on history"}</button>
      {proposal.test_run_id && <Link to={testRunHref(proposal.test_run_id)}>See the run in the Dojo</Link>}
    </div>}
    {rationale && <RationaleFields rationale={rationale} stacked />}
    {note && <section>
      <h4>{rationale ? "Author's note" : "Reason"}</h4>
      <p className="pl-brief-note">{note}</p>
    </section>}
  </div>;
}
