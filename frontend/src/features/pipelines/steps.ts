import type { PipelineComponent, PipelineNode } from "./contracts";

export type StepFamily = "normalize" | "reduce" | "route" | "transform" | "input" | "detector" | "policy" | "output";

/** Menu order: the steps people add most come first, the one-per-pipeline steps last. */
export const STEP_FAMILIES: { id: StepFamily; label: string }[] = [
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

/** What a step does, by its kind and component; unknown transforms stay "Transform". */
export function stepFamily(kind: PipelineNode["kind"], component: string): StepFamily {
  if (kind === "source") return "input";
  if (kind === "merge" || ROUTES.has(component)) return "route";
  if (kind !== "transform") return kind;
  if (/(standard|min_max)_scaler$/.test(component)) return "normalize";
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
  "static.standard_scaler": "Center and scale with training statistics.",
  "adaptive.standard_scaler": "Center and scale with running statistics.",
  "static.min_max_scaler": "Scale to 0 to 1 with training bounds.",
  "adaptive.min_max_scaler": "Scale to 0 to 1 with the bounds seen so far.",
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
