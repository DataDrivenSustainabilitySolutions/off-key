import { useCallback, useState } from "react";
import { usePollingLoop } from "@/hooks/use-polling";
import type { PipelineProposalSummary, ProposalTest } from "@/types/pipelines.generated";
import { pipelinesApi } from "./api";

/** What became of a proposal and who decided it, or nothing while it waits. A note that came with the decision reads on its own. */
export function proposalOutcome(proposal: PipelineProposalSummary): string {
  if (proposal.status === "open") return "";
  if (proposal.status === "withdrawn") return "Withdrawn by its author";
  return `${proposal.status === "accepted" ? "Accepted" : "Declined"}${proposal.decided_by ? ` by ${proposal.decided_by}` : ""}`;
}

/** The colour of a proposal's state: waiting asks for attention, a decision says how it went. */
export const proposalTone = (proposal: PipelineProposalSummary) =>
  ({ open: "warning", accepted: "positive", declined: "danger", withdrawn: "neutral" } as const)[proposal.status];

/** The Dojo's runs, with the test a proposal was handed in with picked out. */
export const testRunHref = (runId: string) => `/dojo?run=${encodeURIComponent(runId)}`;

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

/**
 * The one line a reviewer reads first, under the name: the author's summary, or where an older
 * proposal has none, what it watches.
 */
export const proposalLede = (proposal: PipelineProposalSummary) =>
  proposal.rationale?.summary || proposal.rationale?.watches || proposal.reason;

/** A duration as a reviewer says it: seconds, minutes or hours. */
export function duration(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 90 * 60) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

/** How many of the planted faults raised an alarm, or nothing when the test planted none. */
export function faultsCaught(test: ProposalTest): { caught: number; total: number } | undefined {
  if (!test.faults?.length) return undefined;
  return { caught: test.faults.filter((fault) => fault.outcome === "detected").length, total: test.faults.length };
}
