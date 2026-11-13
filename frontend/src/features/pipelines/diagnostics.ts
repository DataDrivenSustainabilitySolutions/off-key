import type { PipelineNodePreview, PipelineRuntimeState } from "../../types/pipelines.generated";

/** Generated from RADAR's runtime state model, which RADAR's tests validate against. */
export type NodePass = PipelineNodePreview;
export type PipelineState = PipelineRuntimeState;

const REJECTIONS: Record<string, string> = {
  non_finite: "not a finite number",
  out_of_domain: "outside the function's domain",
  out_of_range: "outside the range",
  // A step that reads time got an observation measured no later than its previous one.
  out_of_order: "not later than the one before",
  // A learned step or the detector failed, and nothing it had learned changed.
  error: "with an error",
};

/** "Skipped 3 observations: 2 outside the range, 1 not a finite number." */
export function rejectionSummary(rejections: Record<string, number> | undefined) {
  const entries = Object.entries(rejections ?? {}).filter(([, count]) => count > 0);
  if (!entries.length) return undefined;
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  const reasons = entries.map(([reason, count]) => `${count} ${REJECTIONS[reason] ?? reason.replace(/_/g, " ")}`);
  return `Skipped ${total} observation${total === 1 ? "" : "s"}: ${reasons.join(", ")}.`;
}
