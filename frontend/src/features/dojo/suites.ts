import type { StudyComparison, StudySummary, StudyTotals, SuiteDataset } from "@/types/dojo.generated";

export type StudyMetric = StudyComparison["metric"];

export const STUDY_METRICS: { id: StudyMetric; label: string }[] = [
  { id: "vus_pr", label: "VUS-PR" },
  { id: "pr_auc", label: "PR-AUC" },
  { id: "auroc", label: "AUROC" },
  { id: "detection_rate", label: "Detection rate" },
];

export const formatScore = (value: number | null | undefined) => value == null ? "–" : value.toFixed(3);

/** How many of a study's runs are in each state, in words. */
export function studyProgress(study: Pick<StudySummary, "runs" | "complete" | "metrics_pending">) {
  const count = (status: string) => study.runs[status] ?? 0;
  const waiting = count("queued") + count("running");
  const failed = count("failed") + count("cancelled");
  const parts = [];
  if (waiting) parts.push(`${waiting} waiting or running`);
  if (failed) parts.push(`${failed} failed or cancelled`);
  if (!waiting && study.metrics_pending) parts.push(`metrics for ${study.metrics_pending} still to calculate`);
  return parts.length ? parts.join(", ") : study.complete ? "Complete" : "Incomplete";
}

/** "3 of 4" for a metric that only some runs could score. */
export const scoredOf = (totals: StudyTotals, runs: number) =>
  runs < totals.runs_scored ? ` (${runs} of ${totals.runs_scored})` : "";

/** The series names every dataset of a suite has, which a study can bind a slot to for all of them. */
export function sharedSeriesNames(items: Pick<SuiteDataset, "series_names">[]) {
  const [first, ...rest] = items;
  if (!first) return [];
  return first.series_names.filter(name => rest.every(item => item.series_names.includes(name)));
}

/** A p-value in words that do not overstate it. */
export function describePValue(value: number | null | undefined) {
  if (value == null) return "Too few datasets differ to test";
  return value < 0.05 ? `p = ${value.toPrecision(2)}, unlikely to be chance` : `p = ${value.toPrecision(2)}, could be chance`;
}
