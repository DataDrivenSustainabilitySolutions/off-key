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
  elementwise: boolean;
};

const strings = (value: JsonValue | undefined) =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : undefined;

/** Steps with Applies to and Result. A Formula picks its features in its own editor. */
export const hasScope = (component?: PipelineComponent) =>
  component?.id !== "prepare.formula" && !!component?.fields.some((field) => field.name === "apply_to");

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

/** A quantile as a percentage in suffix characters, as core writes it: 0.9 is 90, 0.999 is 99p9. */
const quantileLabel = (quantile: number) =>
  (quantile * 100).toFixed(6).replace(/\.?0+$/, "").replace(".", "p");

/** The short name a Prepare step gives added features, following its settings, as core
 * names them: smooth10, diff1, mean60, q90_60, log. Other steps carry theirs in the catalog. */
export function defaultSuffix(node: PipelineNode, component?: PipelineComponent): string | undefined {
  const value = (name: string) => setting(node, component, name);
  switch (node.component) {
    case "prepare.smooth": return `smooth${value("window_size")}`;
    case "prepare.despike": return "despiked";
    case "prepare.change": return `${CHANGE_SUFFIXES[String(value("mode"))] ?? "diff"}${value("lag")}`;
    case "prepare.rolling": return value("statistic") === "quantile"
      // Two quantiles of one window keep apart: q10_60 and q90_60.
      ? `q${quantileLabel(Number(value("quantile") ?? 0.5))}_${value("window_size")}`
      : `${value("statistic")}${value("window_size")}`;
    case "prepare.accumulate": return value("function") === "sum" ? "total" : `running_${value("function")}`;
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
  return { applyTo: strings(node.params.apply_to), add, suffix, elementwise: !!suffixField };
}

export const addedName = (feature: string, suffix: string) => `${feature}_${suffix}`;

/** "a", "a and b", "a, b and c", or the first few and a count of the rest. */
export const listed = (names: string[], limit = 3) =>
  names.length <= limit
    ? names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`
    : `${names.slice(0, limit).join(", ")} and ${names.length - limit} more`;

/** Errors block applying a design; warnings are shown and do not. */
export const isWarning = (issue: Pick<PipelineIssue, "severity">) => issue.severity === "warning";
