import { fieldApplies } from "@/components/parameter-editor/types";
import type { PipelineComponent, PipelineNode } from "./contracts";
import { hasScope, SCOPE_FIELDS, setting, TIME_FEATURES } from "./scope";

/** Where the catalog files a step. "transform" is for a transform the catalog does not list. */
export type StepFamily = PipelineComponent["group"] | "transform";

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

/** As far as a kind alone tells, for a step whose component the catalog does not list. */
const BY_KIND: Record<PipelineNode["kind"], StepFamily> = {
  source: "input", transform: "transform", merge: "route", detector: "detector",
  calibration: "calibration", policy: "policy", output: "output",
};

/** What a step does. The catalog says so for every component it lists. */
export const stepFamily = (node: Pick<PipelineNode, "kind">, component: Pick<PipelineComponent, "group"> | undefined): StepFamily =>
  component?.group ?? BY_KIND[node.kind];

export const familyLabel = (family: StepFamily) =>
  STEP_FAMILIES.find((item) => item.id === family)?.label ?? "Transform";

/** Settings with controls of their own: the formula editor, For each, Result, Name, Suffix,
 * the feature a Rolling relation compares with, an Expected value's target and the list of
 * time features. */
const OWN_CONTROLS: Record<string, Set<string>> = {
  "prepare.aggregate": new Set(["name"]),
  "prepare.formula": new Set(["expression", "name", "result", "apply_to", "suffix"]),
  "prepare.gate": new Set(["condition"]),
  "prepare.mute": new Set(["condition"]),
  "prepare.condition": new Set(["condition", "name"]),
  "prepare.set": new Set(["expression", "name"]),
  "prepare.calculate": new Set(["formulas"]),
  "prepare.accumulate": new Set(["reset_when"]),
  "prepare.hold": new Set(["update_when"]),
  "prepare.relation": new Set(["against"]),
  "prepare.time": new Set([...TIME_FEATURES.map(([name]) => name), "timezone"]),
  "static.expected_value": new Set(["target", "name"]),
  "adaptive.expected_value": new Set(["target", "name"]),
};
/** Steps that compute or decide by a formula; it is their main setting. */
export const FORMULA_STEPS = new Set([
  "prepare.formula", "prepare.gate", "prepare.mute", "prepare.condition", "prepare.set", "prepare.calculate",
]);
/** Steps that decide by a condition and pass every feature on, so no feature row names them. */
export const DECISION_STEPS = new Set(["prepare.gate", "prepare.mute"]);
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

/** The settings the inspector lists below Applies to and Result: those without a control
 * of their own that apply with the step's other settings. */
export function stepFields(node: PipelineNode, component: PipelineComponent) {
  const own = node.kind === "calibration" ? CALIBRATION_CONTROLS : OWN_CONTROLS[node.component];
  return component.fields.filter((field) =>
    !(hasScope(component) && SCOPE_FIELDS.has(field.name)) && !own?.has(field.name)
    && fieldApplies(field, setting(node, component, field.shown_when?.field ?? "")));
}
