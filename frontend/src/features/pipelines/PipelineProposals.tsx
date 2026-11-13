import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import { Breadcrumb } from "@/components/Breadcrumb";
import { RelativeTime } from "@/components/RelativeTime";
import { getErrorMessage } from "@/lib/errors";
import type { PipelineProposalSummary } from "@/types/pipelines.generated";
import { pipelinesApi } from "./api";
import { proposalOutcome } from "./proposals";

/** The designs handed in for a decision. Reviewing one opens it in the setup. */
export function PipelineProposalList({ onReview, onBack }: {
  onReview: (proposal: PipelineProposalSummary) => void;
  onBack: () => void;
}) {
  const [decided, setDecided] = useState(false);
  const [result, setResult] = useState<{ decided: boolean; items: PipelineProposalSummary[] }>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const items = result?.decided === decided ? result.items : undefined;

  useEffect(() => {
    const controller = new AbortController();
    void pipelinesApi.proposals(decided ? undefined : "open", controller.signal).then(
      (next) => { if (!controller.signal.aborted) { setResult({ decided, items: next }); setError(""); } },
      (reason) => { if (!controller.signal.aborted) setError(getErrorMessage(reason)); },
    );
    return () => controller.abort();
  }, [decided, retry]);

  return <section className="pl-library" aria-label="Proposals">
    <Breadcrumb steps={[{ label: "Monitoring", onClick: onBack }]} current="Proposals" />
    <div className="pl-header">
      <div>
        <h1>Proposals</h1>
        <p className="pl-help">Designs an agent or a member handed in for a decision. Review one to start it or decline it.</p>
      </div>
    </div>
    <div className="pl-library-tools">
      <label className="pl-check">
        <input type="checkbox" checked={decided} onChange={(event) => setDecided(event.target.checked)} />
        Show decided proposals
      </label>
    </div>
    {error && <p role="alert" className="pl-error">{error}
      <button type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button>
    </p>}
    {!items ? !error && <p role="status">Loading proposals…</p> : !items.length
      ? <p className="pl-empty">{decided ? "No proposals yet." : "No proposal waits for a decision."}</p>
      : <ul className="pl-library-list pl-proposal-list">
        {items.map((proposal) => <li key={proposal.id}>
          <button type="button" onClick={() => onReview(proposal)} aria-label={`Review ${proposal.name}`}>
            <strong>{proposal.name}</strong>
            <span>{proposal.reason}</span>
            <small>Proposed by {proposal.author} <RelativeTime value={proposal.created_at} />
              {proposal.replace_monitor_id && " · Replaces a running service"}</small>
            {proposal.status !== "open" && <small>{proposalOutcome(proposal)}</small>}
          </button>
        </li>)}
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
  const [declining, setDeclining] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const open = proposal.status === "open";

  const decline = async () => {
    setBusy(true); setError("");
    try {
      await pipelinesApi.decideProposal(proposal.id, { status: "declined", note: note.trim() || null });
      toast.success(`Declined ${proposal.name}.`, { id: "pipeline-proposal" });
      onDeclined();
    } catch (reason) { setError(getErrorMessage(reason)); }
    finally { setBusy(false); }
  };

  return <div className="pl-proposal" role="group" aria-label={`Proposal by ${proposal.author}`}>
    <div className="pl-proposal-text">
      <p><strong>Proposed by {proposal.author}</strong> <RelativeTime value={proposal.created_at} /></p>
      <p>{proposal.reason}</p>
      <p className="pl-proposal-state">{open ? canDecide ? "Starting the service accepts the proposal." : "It waits for a member who manages monitors."
        : `${proposalOutcome(proposal)}.`}</p>
      {error && <p role="alert" className="pl-field-error">{error}</p>}
    </div>
    {open && canDecide && (declining
      ? <form className="pl-proposal-decline" onSubmit={(event) => { event.preventDefault(); void decline(); }}>
        <input autoFocus aria-label="Why you decline" placeholder="Why, for the author (optional)" maxLength={2000}
          value={note} disabled={busy} onChange={(event) => setNote(event.target.value)} />
        <button type="submit" disabled={busy}>Decline proposal</button>
        <button type="button" disabled={busy} onClick={() => { setDeclining(false); setError(""); }}>Cancel</button>
      </form>
      : <button type="button" onClick={() => setDeclining(true)}>Decline</button>)}
  </div>;
}
