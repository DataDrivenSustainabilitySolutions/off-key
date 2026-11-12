import type { PipelineComponent, PipelineNode } from "./contracts";
import { hasScope, SCOPE_FIELDS, setting, TIME_FEATURES } from "./scope";

export type StepFamily =
  "prepare" | "combine" | "normalize" | "reduce" | "route" | "transform" | "input" | "forecaster" | "detector"
  | "calibration" | "policy" | "output";

/** Menu order: the steps people add most come first, the one-per-pipeline steps last.
 * Prepare steps lead because they run first, before anything learns; Combine steps
 * follow, because they usually unite features that were prepared one by one. */
export const STEP_FAMILIES: { id: StepFamily; label: string }[] = [
  { id: "prepare", label: "Prepare" },
  { id: "combine", label: "Combine" },
  { id: "normalize", label: "Normalize" },
  { id: "reduce", label: "Reduce" },
  { id: "route", label: "Route" },
  { id: "transform", label: "Transform" },
  { id: "input", label: "Input" },
  { id: "forecaster", label: "Forecaster" },
  { id: "detector", label: "Detector" },
  { id: "calibration", label: "Calibration" },
  { id: "policy", label: "Detection rule" },
  { id: "output", label: "Evidence output" },
];

// A Gate decides whether an observation goes on, so it sits with the routes.
const ROUTES = new Set(["features.select", "features.rename", "features.passthrough", "prepare.gate"]);
/** Steps that compute one feature from the features that arrive. */
const COMBINE_STEPS = new Set([
  "prepare.aggregate", "prepare.formula", "prepare.constant", "prepare.condition", "prepare.set", "prepare.calculate",
]);

/** Steps that run once per observation, in arrival order, before anything learns. */
const isPrepare = (component: string) => component.startsWith("prepare.");

/** Detectors that score one feature against the forecast made for it. Some learn
 * as data arrives; a pretrained one ("forecast.") is ready from the first values. */
const isForecaster = (component: string) => component.endsWith("_forecaster") || component.startsWith("forecast.");

/** What a step does, by its kind and component; unknown transforms stay "Transform". */
export function stepFamily(kind: PipelineNode["kind"], component: string): StepFamily {
  if (kind === "source") return "input";
  if (kind === "merge" || ROUTES.has(component)) return "route";
  if (kind === "detector" && isForecaster(component)) return "forecaster";
  if (kind !== "transform") return kind;
  if (COMBINE_STEPS.has(component)) return "combine";
  if (isPrepare(component)) return "prepare";
  if (/(standard|min_max|robust)_scaler$/.test(component)) return "normalize";
  if (/(pca|random_projection)$/.test(component)) return "reduce";
  return "transform";
}

export const familyLabel = (family: StepFamily) =>
  STEP_FAMILIES.find((item) => item.id === family)?.label ?? "Transform";

/** One line each for the add-step menu; the catalog's own text is the fallback. */
const DESCRIPTIONS: Record<string, string> = {
  "source.aligned": "The chosen readings as one observation.",
  "features.select": "Keep only the chosen features.",
  "features.rename": "Give features new names.",
  "features.passthrough": "Forward features unchanged.",
  "features.merge": "Join branches into one feature list.",
  "prepare.smooth": "Average recent values to calm noise, over observations or over time.",
  "prepare.despike": "Replace sudden spikes with the recent median.",
  "prepare.change": "Add the change since earlier observations.",
  "prepare.rolling": "Add a sum, quantile, spread, trend, shape or score of recent values.",
  "prepare.accumulate": "Keep a running total, minimum, maximum or count, and start over on a condition.",
  "prepare.hold": "Keep each value from the last time a condition held.",
  "prepare.relation": "Add how features move with one other feature: correlation, slope or residual.",
  "prepare.math": "Take a log, root, absolute value, square or scale.",
  "prepare.range": "Clip values to a range, or skip observations outside it.",
  "prepare.aggregate": "Combine features into their mean, sum, extreme, spread or range.",
  "prepare.formula": "Compute a feature from others, such as dc_voltage * dc_current.",
  "prepare.gate": "Learn and score only while a condition holds.",
  "prepare.constant": "Add a named constant to use in later steps.",
  "prepare.condition": "Turn a comparison or Boolean condition into a 1 or 0 feature.",
  "prepare.set": "Calculate or replace one feature, keeping the others.",
  "prepare.calculate": "Calculate several named features, one formula per line.",
  "prepare.time": "Add the seconds since the previous observation, the hour or the weekday.",
  "static.standard_scaler": "Center and scale with training statistics.",
  "adaptive.standard_scaler": "Center and scale with running statistics.",
  "static.min_max_scaler": "Scale to 0 to 1 with training bounds.",
  "adaptive.min_max_scaler": "Scale to 0 to 1 with the bounds seen so far.",
  "static.robust_scaler": "Center on the median and divide by the quartile range of training data.",
  "adaptive.robust_scaler": "Center on the recent median and divide by the recent quartile range.",
  "static.pca": "Keep the main directions of the training data.",
  "adaptive.uncentered_pca": "Keep the main directions, updated as data arrives.",
  "static.random_projection": "Fewer dimensions through a fixed random map.",
  "adaptive.random_projection": "Fewer dimensions through a fixed random map.",
  "detector:aberrant_seasonal_naive_forecaster": "Expect the value one cycle ago and score the miss.",
  "detector:aberrant_holt_winters_forecaster": "Expect a level, a trend and a repeating cycle, and score the miss.",
  "forecast.timestral": "Expect what a pretrained model forecasts from the recent values and score the miss.",
  "policy.martingale": "Alarm when evidence of change builds up.",
  "policy.quantile": "Alarm when scores pass a calibrated threshold.",
  "policy.exceedance": "Alarm when scores stay above the boundary the calibration step adapts.",
  "calibrate.fixed_split": "Rank every score against the calibration window, which then stays as it is.",
  "output.evidence": "Store scores, evidence and alarms.",
};

export const stepDescription = (component: PipelineComponent) =>
  DESCRIPTIONS[component.id] ?? component.description;

/** Settings with controls of their own: the formula editor, For each, Result, Name, Suffix,
 * the feature a Rolling relation compares with and the list of time features. */
const OWN_CONTROLS: Record<string, Set<string>> = {
  "prepare.aggregate": new Set(["name"]),
  "prepare.formula": new Set(["expression", "name", "result", "apply_to", "suffix"]),
  "prepare.gate": new Set(["condition"]),
  "prepare.condition": new Set(["condition", "name"]),
  "prepare.set": new Set(["expression", "name"]),
  "prepare.calculate": new Set(["formulas"]),
  "prepare.accumulate": new Set(["reset_when"]),
  "prepare.hold": new Set(["update_when"]),
  "prepare.relation": new Set(["against"]),
  "prepare.time": new Set([...TIME_FEATURES.map(([name]) => name), "timezone"]),
};
/** Steps that compute or decide by a formula; it is their main setting. */
export const FORMULA_STEPS = new Set(["prepare.formula", "prepare.gate", "prepare.condition", "prepare.set", "prepare.calculate"]);
/** Steps that work on each feature and read a condition as well, below their own settings. */
export const CONDITION_STEPS = new Set(["prepare.accumulate", "prepare.hold"]);
// Combine detectors has its own control, shown once the design has two detectors.
const CALIBRATION_CONTROLS = new Set(["fusion"]);

/** How the calibration step makes one value from several detectors, in the composer's words. */
export const FUSION_CHOICES = [
  { value: "max", label: "Strongest", help: "The most surprised detector decides, so a change one detector sees is enough." },
  { value: "mean", label: "Average", help: "Their mean decides, so a change has to show in several detectors, or strongly in one." },
] as const;

export const fusionChoice = (node: PipelineNode) =>
  FUSION_CHOICES.find((choice) => choice.value === node.params.fusion) ?? FUSION_CHOICES[0];

/** Settings a step does not read as it is set: a quantile unless Rolling takes one, scale and
 * offset unless Math is linear, and a Smooth's window or time constant, whichever its method leaves. */
function unread(node: PipelineNode, component: PipelineComponent): string[] {
  const value = (name: string) => setting(node, component, name);
  switch (node.component) {
    case "prepare.rolling": return value("statistic") === "quantile" ? [] : ["quantile"];
    case "prepare.math": return value("function") === "linear" ? [] : ["scale", "offset"];
    case "prepare.smooth": return [value("method") === "time_constant" ? "window_size" : "time_constant"];
  }
  return [];
}

/** The settings the inspector lists below Applies to and Result: those without a control
 * of their own that the step reads as it is set. */
export function stepFields(node: PipelineNode, component: PipelineComponent) {
  const own = node.kind === "calibration" ? CALIBRATION_CONTROLS : OWN_CONTROLS[node.component];
  const hidden = unread(node, component);
  return component.fields.filter((field) =>
    !(hasScope(component) && SCOPE_FIELDS.has(field.name)) && !own?.has(field.name) && !hidden.includes(field.name));
}
