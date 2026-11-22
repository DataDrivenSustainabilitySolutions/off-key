import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import * as Popover from "@radix-ui/react-popover";
import { ChevronLeft, FlaskConical, Play, TriangleAlert } from "lucide-react";
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
import { faultsCaught, proposalLede, proposalOutcome, proposalTone, testRunHref } from "./proposals";
import { AuthorChip } from "../workspace/RationaleCard";
import { FaultDots, ProposalSections } from "./ProposalSections";

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
    <Popover.Trigger className="mn-primary" aria-label={label} disabled={!!blocked} aria-describedby={blocked ? describedBy : undefined}>
      <Play size={14} aria-hidden="true" />{update ? "Update" : "Start"}
    </Popover.Trigger>
    <Popover.Portal><Popover.Content className="pl-library pl-decision" align="end" sideOffset={8} collisionPadding={12} aria-label={label}>
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
function ProposalActions({ proposal, full, replaced, review, onDeclined, onStarted }: {
  proposal: PipelineProposalSummary;
  full: boolean;
  replaced?: ActiveService;
  /** The way into the design, which stands between the two decisions. */
  review: ReactNode;
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
    <DeclineProposal proposal={proposal} named onDeclined={onDeclined} />
    {review}
    <StartProposal proposal={proposal} blocked={blocked} describedBy={reason} replaced={replaced} apply={apply} />
    {blocked && <small id={reason} className="pl-proposal-hint">{blocked}</small>}
    {/* A refused start leaves no request behind; the actions stay, with the reason, to try again. */}
    {apply.error && <p role="alert" className="pl-field-error">{apply.error}</p>}
  </>;
}

/** How much of the history a design alarmed in, which the faults it caught read against. */
const inAlarm = (share: number) => share === 0 ? "never" : share < 0.01 ? "< 1 %" : `${Math.round(share * 100)} %`;

/** One proposal in the list: its name, the line that says what it is for, and the test in brief. */
function ProposalItem({ proposal, selected, stated, onSelect }: {
  proposal: PipelineProposalSummary;
  selected: boolean;
  stated: boolean;
  onSelect: () => void;
}) {
  const faults = proposal.test && faultsCaught(proposal.test);
  const name = useId();
  const lede = useId();
  return <li>
    <button type="button" className="pl-desk-item" aria-current={selected || undefined} aria-labelledby={name} aria-describedby={lede} onClick={onSelect}>
      <strong id={name}>{proposal.name}</strong>
      <em id={lede}>{proposalLede(proposal)}</em>
      <span className="pl-desk-item-meta">
        {stated && <span className={`mn-state mn-state--${proposalTone(proposal)}`}>{proposalOutcome(proposal) || "Waiting"}</span>}
        {proposal.test
          ? <><FaultDots test={proposal.test} />
            <span>{faults ? `${faults.caught} of ${faults.total} caught` : "No faults planted"}</span>
            {proposal.test.alarm_share != null && <span>{`${inAlarm(proposal.test.alarm_share)} in alarm`}</span>}</>
          : <span>{proposal.test_run_id ? "Tested" : "Not tested"}</span>}
        {!!proposal.missing_readings?.length && <span className="pl-desk-item-warn"><TriangleAlert size={12} aria-hidden="true" />Readings gone</span>}
      </span>
    </button>
  </li>;
}

/**
 * The proposal picked in the list, as a short report with the decision at its head: who handed it in,
 * its name and the line that says what it is for, then the readings, the evidence and the rest.
 */
function ProposalDetail({ proposal, canDecide, full, replaced, onReview, onDeclined, onStarted, onClose }: {
  proposal: PipelineProposalSummary;
  canDecide: boolean;
  full: boolean;
  replaced?: ActiveService;
  onReview: () => void;
  onDeclined: () => void;
  onStarted?: (id: string) => void;
  onClose: () => void;
}) {
  const title = useId();
  const missing = missingReadings(proposal);
  const open = proposal.status === "open";
  return <article className="pl-desk-detail" aria-labelledby={title}>
    <button type="button" className="pl-desk-back" onClick={onClose}><ChevronLeft size={14} aria-hidden="true" />All proposals</button>
    <header className="pl-desk-head">
      <div className="pl-desk-title">
        <ProposalByline proposal={proposal} replaced={replaced} />
        <h2 id={title}>{proposal.name}</h2>
        <p className="pl-desk-lede">{proposalLede(proposal)}</p>
      </div>
      <div className="pl-proposal-actions">
        {open && canDecide && <ProposalActions proposal={proposal} full={full} replaced={replaced} onDeclined={onDeclined} onStarted={onStarted}
          review={<button type="button" onClick={onReview}>Review design</button>} />}
        {(!open || !canDecide) && <button type="button" onClick={onReview}>{open ? "Review design" : "View design"}</button>}
      </div>
    </header>
    {!open && <ProposalDecision proposal={proposal} />}
    {open && !canDecide && <p className="pl-review-quiet">It waits for a member who manages monitors.</p>}
    {missing && <p className="pl-proposal-missing"><TriangleAlert size={14} aria-hidden="true" />{missing}</p>}
    <ProposalSections proposal={proposal} />
  </article>;
}

/**
 * The designs handed in for a decision, as a review desk: the list on the left, the one picked as a
 * short report on the right. A phone shows the list, and the report as a page of its own.
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
  const [picked, setPicked] = useState<string>();
  // A phone shows the list until a proposal is opened, then that proposal alone.
  const [reading, setReading] = useState(false);

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
  // The one picked, or the first while none is: a decided one leaves the list and the next takes its place.
  const selected = items?.find((item) => item.id === picked) ?? items?.[0];
  const choose = (id: string) => { setPicked(id); setReading(true); };

  return <section className="pl-library pl-proposals" aria-label="Proposals" data-reading={reading && !!selected || undefined}>
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
    <p className="pl-proposals-intro"><span className="pl-proposals-about">Monitors designed and tested on history, waiting for a decision.
      {canDecide ? " Read one, start it as proposed, or decline it." : " Read one and review its design."}</span>
      {full && " Starting a proposal needs a free place: stop a monitor first, or start one that replaces a running service."}</p>
    <div className="mn-list-tools pl-proposals-tools">
      <div className="mn-filters" aria-label="Filter proposals">
        {filters.map((item) => <button key={item.label} type="button" aria-pressed={decided === item.id} onClick={() => { setDecided(item.id); setReading(false); }}>
          {item.label}{item.count !== undefined && <> <span className="mn-filter-count">{item.count}</span></>}
        </button>)}
      </div>
    </div>
    {error && <p role="alert" className="pl-error">{error}
      <button type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button>
    </p>}
    {!items ? !error && <p className="mn-loading" role="status">Loading proposals…</p> : !selected
      ? <div className="mn-empty"><h2>{decided ? "No proposals yet" : "Nothing to decide"}</h2>
        <p>{decided ? "Proposals appear here when an agent or a member hands in a design."
          : "No proposal waits for a decision."}</p></div>
      : <div className="pl-desk">
        <ul className="pl-desk-list" aria-label={decided ? "All proposals" : "Waiting proposals"}>
          {items.map((proposal) => <ProposalItem key={proposal.id} proposal={proposal} selected={proposal.id === selected.id}
            stated={decided} onSelect={() => choose(proposal.id)} />)}
        </ul>
        <ProposalDetail key={selected.id} proposal={selected} canDecide={canDecide} full={full}
          replaced={services.find((service) => service.id === selected.replace_monitor_id)}
          onReview={() => onReview(selected)} onStarted={onStarted} onClose={() => setReading(false)}
          onDeclined={() => { setReading(false); setRetry((value) => value + 1); }} />
      </div>}
  </section>;
}

/** Said above the canvas while the proposal's design is open: what keeps it from starting as it was handed in. */
export function PipelineProposalWarning({ proposal }: { proposal: PipelineProposalSummary }) {
  const missing = missingReadings(proposal);
  return missing ? <p className="pl-warning" role="status">{missing} Choose other readings at the Input step.</p> : null;
}

/**
 * The proposal beside its design, for the member who decides: the line that says what it is for,
 * where it stands, who handed it in and as what, the way to the test it came with, and the same
 * report as in the list. The decision itself is made with the setup's own Start and the Decline beside it.
 */
export function PipelineProposalBrief({ proposal, canDecide, replaced, onOpenTest }: {
  proposal: PipelineProposalSummary;
  canDecide: boolean;
  replaced?: ActiveService;
  /** Opens the test beside the design, where the setup has one: for members who may use the Dojo. */
  onOpenTest?: () => void;
}) {
  const open = proposal.status === "open";
  return <div className="pl-brief" role="group" aria-label={`Proposal by ${proposedBy(proposal)}`}>
    {/* On a phone the brief is a page of its own and opens with the name the design was handed in under. */}
    <p className="pl-brief-name">{proposal.name}</p>
    <p className="pl-desk-lede">{proposalLede(proposal)}</p>
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
    <ProposalSections proposal={proposal} compact />
  </div>;
}
