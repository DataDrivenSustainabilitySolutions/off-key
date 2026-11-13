import { fieldDefaults } from "@/components/parameter-editor/types";
import type { PipelineComponent, PipelineDefinition } from "./contracts";
import { setNodeParams, type GraphDocument } from "./model";
import { componentFor } from "./semantics";
import { roughDuration } from "./startup";

/** How often a design's scores lie above its boundary, as its own settings state it. */
export type AlarmBudget = {
  /** The step that holds the setting, and the setting's name there. */
  node: string;
  field: "alpha" | "quantile";
  /** The share of scores above the boundary. */
  share: number;
  /** What the calibration method promises about that share. */
  promise?: PipelineComponent["coverage"];
  /** The smallest share the calibration scores can tell apart, where the boundary is one of them. */
  finest?: number;
  /** Scores in a row above the boundary that make an alarm. */
  consecutive: number;
};

const amount = (value: unknown, fallback: number) => typeof value === "number" && Number.isFinite(value) ? value : fallback;

/** The alarm budget of a design, or nothing where it has none to set: a design that is not
 * complete yet, and one that alarms on a conformal martingale, which follows a run of rare
 * values instead of a share of scores. */
export function alarmBudget(definition: PipelineDefinition, components: PipelineComponent[]): AlarmBudget | undefined {
  const calibration = definition.nodes.find((node) => node.kind === "calibration");
  const policy = definition.nodes.find((node) => node.kind === "policy");
  if (!calibration || !policy) return undefined;
  const method = componentFor(calibration, components);
  const fields = method?.fields ?? [];
  const promise = method?.coverage ?? undefined;
  if (fields.some((field) => field.name === "alpha")) {
    const share = amount({ ...fieldDefaults(fields), ...calibration.params }.alpha, NaN);
    if (!(share > 0 && share < 1)) return undefined;
    const consecutive = policy.component === "policy.exceedance" ? amount(policy.params.consecutive, 1) : 1;
    return { node: calibration.id, field: "alpha", share, promise, consecutive };
  }
  if (policy.component !== "policy.quantile") return undefined;
  // A boundary at the largest of n calibration scores is passed about once in n + 1 scores.
  const finest = 1 / (definition.settings.calibration_window_size + 1);
  const quantile = amount(policy.params.quantile, 1);
  return { node: policy.id, field: "quantile", share: Math.max(1 - quantile, finest), promise, finest, consecutive: 1 };
}

/** The design with another share of scores above its boundary. A boundary taken from the
 * calibration scores cannot lie above the largest of them, so a smaller share than that
 * leaves it there. */
export function withAlarmShare(document: GraphDocument, budget: AlarmBudget, share: number): GraphDocument {
  const node = document.definition.nodes.find((item) => item.id === budget.node);
  if (!node || !(share > 0 && share < 1)) return document;
  const value = budget.field === "alpha" ? Number(share.toPrecision(6))
    : share <= (budget.finest ?? 0) ? 1 : Number((1 - share).toPrecision(12));
  return setNodeParams(document, node.id, { ...node.params, [budget.field]: value });
}

export const BUDGET_PERIODS = [
  { id: "hour", label: "per hour", seconds: 3600 },
  { id: "day", label: "per day", seconds: 86_400 },
  { id: "week", label: "per week", seconds: 604_800 },
] as const;
export type BudgetPeriod = (typeof BUDGET_PERIODS)[number];

/** How many scores lie above the boundary in a period, at one observation every `interval` seconds. */
export const budgetCount = (share: number, interval: number, period: BudgetPeriod) => share * period.seconds / interval;

/** The share that gives so many in a period. */
export const budgetShare = (count: number, interval: number, period: BudgetPeriod) => count * interval / period.seconds;

/** The period in which a budget is a number worth reading: the shortest that holds one at least. */
export function budgetPeriod(share: number, interval: number): BudgetPeriod {
  return BUDGET_PERIODS.find((period) => budgetCount(share, interval, period) >= 1) ?? BUDGET_PERIODS[BUDGET_PERIODS.length - 1]!;
}

/** A count in two digits, which is all an estimate is good for. */
export const budgetNumber = (count: number) => Number(count.toPrecision(2));

/** How many scores one above the boundary comes in: the 100 of "1 in 100". */
export const scoresPerAlarm = (share: number) => Math.max(Math.round(1 / share), 2);

const PROMISE: Record<NonNullable<AlarmBudget["promise"]>, string> = {
  long_run: "It holds over a long run, also when the readings drift.",
  exchangeable: "It holds while the readings behave as they did during calibration.",
  none: "The method aims at it without a guarantee.",
};

/** What a budget counts and how far it can be relied on, for the text under the setting.
 * A calibration window that is too short for the budget (`short`) cannot keep it, which the
 * check says in its own words, so the promise is left out then. */
export function budgetSentence(
  budget: AlarmBudget,
  { interval, gated, short }: { interval?: number; gated?: boolean; short?: boolean } = {},
) {
  const { share, consecutive, finest } = budget;
  return [
    interval
      ? `That is one score in ${scoresPerAlarm(share).toLocaleString()} above the boundary, at one observation every ${roughDuration(interval)}.`
      : "A count per hour appears once the chosen readings report how often they arrive.",
    consecutive > 1
      ? `An alarm takes ${consecutive.toLocaleString()} in a row, so alarms come less often.`
      : "While nothing is wrong, each is a false alarm.",
    budget.promise && !short ? PROMISE[budget.promise] : "",
    // The boundary is the largest calibration score already.
    finest !== undefined && share <= finest ? "Fewer alarms need more calibration observations." : "",
    gated ? "A Gate holds back observations, so there can be fewer." : "",
  ].filter(Boolean).join(" ");
}
