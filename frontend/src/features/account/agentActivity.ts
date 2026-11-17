import type { MonitorSummary, PipelineProposalSummary } from "@/types/pipelines.generated";

const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/**
 * What an agent did, in one line: its proposals and how they were decided, and the running
 * monitors it designed. An agent is known by its name, which no two keys share.
 */
export function agentActivity(name: string, proposals: readonly PipelineProposalSummary[], monitors: readonly MonitorSummary[]): string {
  const own = (author: string | undefined, kind: string | undefined) => kind === "agent" && author?.toLowerCase() === name.toLowerCase();
  const handed = proposals.filter(proposal => own(proposal.author, proposal.author_kind));
  const running = monitors.filter(monitor => monitor.active && own(monitor.origin?.author, monitor.origin?.author_kind));
  const parts: string[] = [];
  if (handed.length) {
    const by = (status: PipelineProposalSummary["status"]) => handed.filter(proposal => proposal.status === status).length;
    const decided = [[by("open"), "waiting"], [by("accepted"), "started"], [by("declined"), "declined"], [by("withdrawn"), "withdrawn"]]
      .filter(([n]) => n).map(([n, word]) => `${n} ${word}`);
    parts.push(`${count(handed.length, "proposal")} (${decided.join(", ")})`);
  }
  if (running.length) {
    const shadow = running.filter(monitor => monitor.shadow).length;
    parts.push(`${count(running.length, "monitor")} running${shadow ? ` (${shadow} in shadow)` : ""}`);
  }
  return parts.length ? parts.join(" · ") : "No proposals or monitors yet";
}
