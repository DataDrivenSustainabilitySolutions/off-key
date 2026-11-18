import type { JsonValue } from "@/types/monitoring";
import type { PipelineIssue } from "@/types/pipelines.generated";
import type { PipelineComponent, PipelineNode } from "./contracts";

/** The settings that say which features a step uses and where its output goes. */
export const SCOPE_FIELDS = new Set(["apply_to", "result", "suffix"]);

export type StepScope = {
  /** The features the step uses; undefined uses every feature that arrives. */
  applyTo?: string[];
  add: boolean;
  /** Steps that map each feature to one value name their added features with it. */
  suffix?: string;
  /** What each feature's added features end in, in output order: the suffix, or for Lags
   * the suffix and each lag (lag1, lag24). */
  endings: string[];
  elementwise: boolean;
};

const strings = (value: JsonValue | undefined) =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : undefined;

/** Steps with Applies to and Result. A Formula picks its features in its own editor. */
export const hasScope = (component?: PipelineComponent) =>
  component?.id !== "prepare.formula" && !!component?.fields.some((field) => field.name === "apply_to");

/** Steps that expect one feature, the target, from the others and give its residual. */
export const isExpectation = (component: string) => component.endsWith(".expected_value");

/** The setting that names the one feature a step sets apart from those it uses: what a
 * Rolling relation compares with, or what an Expected value expects. */
export const apartField = (component: string) =>
  component === "prepare.relation" ? "against" : isExpectation(component) ? "target" : undefined;

/** The name that stands for each feature in a Formula for each feature. */
export const EACH_VARIABLE = "x";

/** The features a Formula for each feature runs on; undefined for a Formula that computes one. */
export const formulaEach = (node: PipelineNode) =>
  node.component === "prepare.formula" ? strings(node.params.apply_to) : undefined;

/** What a Formula for each feature appends to the names it adds. */
export const eachSuffix = (node: PipelineNode) =>
  typeof node.params.suffix === "string" && node.params.suffix ? node.params.suffix : "formula";

/** A setting of the node, or the catalog default it leaves out. */
export function setting(node: PipelineNode, component: PipelineComponent | undefined, name: string): JsonValue | undefined {
  if (node.params[name] !== undefined) return node.params[name];
  const field = component?.fields.find((item) => item.name === name);
  return field?.default ?? undefined;
}

const CHANGE_SUFFIXES: Record<string, string> = { difference: "diff", percent: "pct", lag: "lag" };
const ACCUMULATE_SUFFIXES: Record<string, string> = { sum: "total", min: "running_min", max: "running_max", count: "count" };
const RELATION_SUFFIXES: Record<string, string> = { correlation: "corr", covariance: "cov", slope: "beta", residual: "resid" };

/** A number in suffix characters, as core writes it, to six decimals: 90 is 90, 99.9 is 99p9. */
const numberLabel = (value: number) => value.toFixed(6).replace(/\.?0+$/, "").replace(".", "p");

/** The features each setting of a Time features step adds, in output order, as core names them. */
export const TIME_FEATURES: [setting: string, names: string[]][] = [
  ["elapsed", ["dt"]],
  ["hour", ["hour"]],
  ["weekday", ["weekday"]],
  ["daily_cycle", ["hour_sin", "hour_cos"]],
  ["weekly_cycle", ["weekday_sin", "weekday_cos"]],
];

/** The settings of a Time features step that are switched on, with what each adds. */
export const timeFeatures = (node: PipelineNode, component?: PipelineComponent) =>
  TIME_FEATURES.filter(([name]) => setting(node, component, name) === true);

/** The short name a Prepare step gives added features, following its settings, as core
 * names them: smooth10, smooth60s, diff1, mean60, q90_60, corr60, log. Other steps carry theirs in the catalog. */
export function defaultSuffix(node: PipelineNode, component?: PipelineComponent): string | undefined {
  const value = (name: string) => setting(node, component, name);
  switch (node.component) {
    case "prepare.smooth": return value("method") === "time_constant"
      // Seconds, where the other methods count observations: smooth60s beside smooth10.
      ? `smooth${numberLabel(Number(value("time_constant") ?? 60))}s`
      : `smooth${value("window_size")}`;
    case "prepare.despike": return "despiked";
    case "prepare.lags": return "lag";
    case "prepare.deseason": return "deseasoned";
    case "prepare.cusum": return "cusum";
    case "prepare.change": return `${CHANGE_SUFFIXES[String(value("mode"))] ?? "diff"}${value("lag")}`;
    case "prepare.rolling": return value("statistic") === "quantile"
      // Two quantiles of one window keep apart: q10_60 and q90_60.
      ? `q${numberLabel(Number(value("quantile") ?? 0.5) * 100)}_${value("window_size")}`
      : `${value("statistic")}${value("window_size")}`;
    case "prepare.accumulate": return ACCUMULATE_SUFFIXES[String(value("function"))] ?? "total";
    case "prepare.hold": return "held";
    case "prepare.relation": return `${RELATION_SUFFIXES[String(value("statistic"))] ?? "corr"}${value("window_size")}`;
    case "prepare.math": return value("function") === "linear" ? "scaled" : String(value("function"));
    case "prepare.range": return "clipped";
  }
  const field = component?.fields.find((item) => item.name === "suffix");
  return typeof field?.default === "string" ? field.default : undefined;
}

/** A step's single computed feature, using the same default name as core. */
export function combinedName(node: PipelineNode, component?: PipelineComponent): string | undefined {
  // A Formula for each feature computes one feature per chosen feature, named by its suffix.
  if (formulaEach(node)) return undefined;
  if (typeof node.params.name === "string" && node.params.name) return node.params.name;
  if (node.component === "prepare.formula") return "formula";
  if (node.component === "prepare.constant") return "constant";
  if (node.component === "prepare.condition") return "condition";
  if (node.component === "prepare.set") return "feature";
  if (node.component === "prepare.aggregate") return String(setting(node, component, "function") ?? "mean");
  // The residual is named after its target, so it has no name before one is chosen.
  if (isExpectation(node.component) && typeof node.params.target === "string" && node.params.target)
    return `${node.params.target}_residual`;
}

const FORMULA_KEYWORDS = new Set(["and", "or", "not"]);

/** Feature names a formula can use as they are; others, and/or/not included, go between backticks. */
export const formulaName = (name: string) =>
  /^[A-Za-z_][A-Za-z0-9_]*$/.test(name) && !FORMULA_KEYWORDS.has(name) ? name : `\`${name}\``;

/** Whether a step adds its output when Result is left at the step's default. */
export const addsByDefault = (component?: PipelineComponent) =>
  component?.fields.find((field) => field.name === "result")?.default === "add";

/** A step's scope as the compiler reads it, with the step's default result and suffix. */
export function stepScope(node: PipelineNode, component?: PipelineComponent): StepScope | undefined {
  if (!component || !hasScope(component)) return undefined;
  const suffixField = component.fields.find((field) => field.name === "suffix");
  const suffix = typeof node.params.suffix === "string" && node.params.suffix
    ? node.params.suffix
    : defaultSuffix(node, component);
  const add = (node.params.result ?? (addsByDefault(component) ? "add" : "replace")) === "add";
  const endings = node.component === "prepare.lags"
    ? lagsOf(node, component).map((lag) => `${suffix ?? "lag"}${lag}${lagUnit(node, component).short}`)
    : [suffix ?? "new"];
  return { applyTo: strings(node.params.apply_to), add, suffix, endings, elementwise: !!suffixField };
}

export const addedName = (feature: string, suffix: string) => `${feature}_${suffix}`;

/** The features a step that adds per feature adds for one feature, as core names them. */
export const addedNames = (feature: string, scope: StepScope) =>
  scope.endings.map((ending) => addedName(feature, ending));

/** A Lags step's lags, sorted and distinct as core keeps them. */
export function lagsOf(node: PipelineNode, component?: PipelineComponent): number[] {
  const value = setting(node, component, "lags");
  const lags = Array.isArray(value) ? value.filter((item): item is number => Number.isInteger(item) && (item as number) > 0) : [];
  return [...new Set(lags)].sort((a, b) => a - b);
}

/** What a lag counts, as core names it: a name appends short to the lag, power_lag15min. */
export const LAG_UNITS: Record<string, { label: string; short: string; seconds?: number }> = {
  observations: { label: "Observations", short: "" },
  seconds: { label: "Seconds", short: "s", seconds: 1 },
  minutes: { label: "Minutes", short: "min", seconds: 60 },
  hours: { label: "Hours", short: "h", seconds: 3600 },
  days: { label: "Days", short: "d", seconds: 86400 },
};

/** The unit a Lags step counts its lags in. */
export const lagUnit = (node: PipelineNode, component?: PipelineComponent) =>
  LAG_UNITS[String(setting(node, component, "unit") ?? "minutes")] ?? LAG_UNITS.minutes!;

/** Lags as people write them: 1-3, 24. */
export function lagText(lags: number[]): string {
  const parts: string[] = [];
  for (let index = 0; index < lags.length;) {
    let end = index;
    while (end + 1 < lags.length && lags[end + 1] === lags[end]! + 1) end += 1;
    // Two neighbours read better apart: 1, 2 rather than 1-2.
    if (end - index >= 2) parts.push(`${lags[index]}-${lags[end]}`);
    else for (let at = index; at <= end; at += 1) parts.push(String(lags[at]));
    index = end + 1;
  }
  return parts.join(", ");
}

/** Lags read from text such as "1-3, 24" or "1 2 3": the lags, or what is wrong. */
export function parseLags(text: string, limit = 3600, most = 24): { lags: number[] } | { error: string } {
  const lags = new Set<number>();
  // "1 - 3" is one range, whatever the spaces around its dash.
  const joined = text.replace(/\s*(?:-|–|\.\.)\s*/g, "-");
  for (const part of joined.split(/[\s,;]+/).filter(Boolean)) {
    const range = /^(\d+)-(\d+)$/.exec(part);
    const [low, high] = range ? [Number(range[1]), Number(range[2])] : [Number(part), Number(part)];
    if (!/^\d+$/.test(part) && !range) return { error: `"${part}" is not a lag. Write whole numbers or ranges, such as 1-3, 24.` };
    if (low < 1 || high > limit) return { error: `Lags run from 1 to ${limit} observations.` };
    if (low > high) return { error: `Write the range ${part} from small to large.` };
    for (let lag = low; lag <= high; lag += 1) {
      lags.add(lag);
      if (lags.size > most) return { error: `At most ${most} lags fit in one step.` };
    }
  }
  if (!lags.size) return { error: "Write at least one lag." };
  return { lags: [...lags].sort((a, b) => a - b) };
}

/** "a", "a and b", "a, b and c", or the first few and a count of the rest. */
export const listed = (names: string[], limit = 3) =>
  names.length <= limit
    ? names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`
    : `${names.slice(0, limit).join(", ")} and ${names.length - limit} more`;

/** Errors block applying a design; warnings are shown and do not. */
export const isWarning = (issue: Pick<PipelineIssue, "severity">) => issue.severity === "warning";
