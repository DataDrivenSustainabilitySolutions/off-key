import type { PipelineComponent, PipelineNode } from "./contracts";
import { hasScope, SCOPE_FIELDS, setting } from "./scope";

export type StepFamily = "prepare" | "normalize" | "reduce" | "route" | "transform" | "input" | "detector" | "policy" | "output";

/** Menu order: the steps people add most come first, the one-per-pipeline steps last.
 * Prepare steps lead because they run first, before anything learns. */
export const STEP_FAMILIES: { id: StepFamily; label: string }[] = [
  { id: "prepare", label: "Prepare" },
  { id: "normalize", label: "Normalize" },
  { id: "reduce", label: "Reduce" },
  { id: "route", label: "Route" },
  { id: "transform", label: "Transform" },
  { id: "input", label: "Input" },
  { id: "detector", label: "Detector" },
  { id: "policy", label: "Decision policy" },
  { id: "output", label: "Evidence output" },
];

const ROUTES = new Set(["features.select", "features.rename", "features.passthrough"]);

/** Steps that run once per observation, in arrival order, before anything learns. */
const isPrepare = (component: string) => component.startsWith("prepare.");

/** What a step does, by its kind and component; unknown transforms stay "Transform". */
export function stepFamily(kind: PipelineNode["kind"], component: string): StepFamily {
  if (kind === "source") return "input";
  if (kind === "merge" || ROUTES.has(component)) return "route";
  if (kind !== "transform") return kind;
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
  "prepare.smooth": "Average recent values to calm noise.",
  "prepare.despike": "Replace sudden spikes with the recent median.",
  "prepare.change": "Add the change since earlier observations.",
  "prepare.rolling": "Add a mean, median, extreme or spread of recent values.",
  "prepare.math": "Take a log, root, absolute value, square or scale.",
  "prepare.range": "Clip values to a range, or skip observations outside it.",
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
  "policy.martingale": "Alarm when evidence of change builds up.",
  "policy.quantile": "Alarm when scores pass a calibrated threshold.",
  "output.evidence": "Store scores, evidence and alarms.",
};

export const stepDescription = (component: PipelineComponent) =>
  DESCRIPTIONS[component.id] ?? component.description;

/** The settings the inspector lists below Applies to and Result. Scale and offset
 * only mean something to a linear Math step, so they stay hidden otherwise. */
export function stepFields(node: PipelineNode, component: PipelineComponent) {
  const fields = hasScope(component)
    ? component.fields.filter((field) => !SCOPE_FIELDS.has(field.name))
    : component.fields;
  if (node.component !== "prepare.math" || setting(node, component, "function") === "linear") return fields;
  return fields.filter((field) => field.name !== "scale" && field.name !== "offset");
}
