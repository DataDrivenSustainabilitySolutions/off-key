import { useCallback, useState } from "react";
import { usePollingLoop } from "@/hooks/use-polling";
import type { PipelineProposalSummary } from "@/types/pipelines.generated";
import { pipelinesApi } from "./api";

/** What became of a proposal, or nothing while it waits. */
export function proposalOutcome(proposal: PipelineProposalSummary): string {
  if (proposal.status === "open") return "";
  if (proposal.status === "withdrawn") return "Withdrawn by its author";
  const outcome = `${proposal.status === "accepted" ? "Accepted" : "Declined"}${proposal.decided_by ? ` by ${proposal.decided_by}` : ""}`;
  return proposal.decision_note ? `${outcome}: ${proposal.decision_note}` : outcome;
}

/** How many proposals wait for a decision; read when enabled and every minute while the page shows. */
export function useOpenProposals(enabled: boolean): number {
  const [count, setCount] = useState(0);
  const [counting, setCounting] = useState(enabled);
  // A count from before the pause says nothing of now, so the next one starts from none.
  if (counting !== enabled) { setCounting(enabled); if (!enabled) setCount(0); }
  const read = useCallback(async (signal: AbortSignal) => {
    try {
      const open = await pipelinesApi.proposals("open", signal);
      if (!signal.aborted) setCount(open.length);
    } catch {
      // The count is a hint. The list itself says when proposals cannot be read.
    }
  }, []);
  usePollingLoop(read, { enabled, intervalMs: 60_000, pauseWhenHidden: true, resumeOnVisible: true });
  return enabled ? count : 0;
}
