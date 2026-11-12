import { fieldDefaults } from "@/components/parameter-editor/types";
import type { PipelineComponent, PipelineDefinition, PipelineNode } from "./contracts";
import { componentFor } from "./semantics";

/** How a step learns. A design has no strategy of its own: what may be combined follows
 * from this, step by step. */
export type Learning = NonNullable<PipelineComponent["learning"]>;

export const FIXED_SPLIT = "calibrate.fixed_split";

const LABELS: Record<Learning, string | undefined> = {
  none: undefined,
  batch: "Fitted once",
  online: "Learns continuously",
  pretrained: "Pretrained",
};

/** What a detector that learns nothing is called: a rule detector scores a feature as it is. */
export const UNTRAINED = "No training";

/** "Fitted once", "Learns continuously" or "Pretrained". A detector that learns nothing
 * says so; a step that does not learn says nothing. */
export const learningLabel = (component: Pick<PipelineComponent, "learning"> & { kind?: PipelineComponent["kind"] } | undefined) =>
  LABELS[component?.learning ?? "none"] ?? (component?.kind === "detector" ? UNTRAINED : undefined);

const learningOf = (node: PipelineNode | undefined, components: PipelineComponent[]): Learning =>
  componentFor(node, components)?.learning ?? "none";

/** The ways the design's detectors learn, without repeats. */
export function detectorLearning(definition: PipelineDefinition, components: PipelineComponent[]): Learning[] {
  return [...new Set(definition.nodes.filter((node) => node.kind === "detector").map((node) => learningOf(node, components)))];
}

/** One phrase for how the design learns, for the header and lists. */
export function learningSummary(definition: PipelineDefinition, components: PipelineComponent[]) {
  const modes = detectorLearning(definition, components);
  if (!modes.length) return "No detector yet";
  return modes.length > 1 ? "Detectors learn differently" : LABELS[modes[0]!] ?? UNTRAINED;
}

/** Whether some detector scores every observation as it arrives: it learns on the stream,
 * is pretrained or follows a rule. */
export const hasStreamingDetector = (definition: PipelineDefinition, components: PipelineComponent[]) =>
  detectorLearning(definition, components).some((mode) => mode !== "batch");

/** What the design's detectors do with the learning window: every one is fitted on it,
 * none learns anything, or some learn as observations arrive. */
export type LearningWindow = "continuous" | "fitted" | "none";

export function learningWindow(definition: PipelineDefinition, components: PipelineComponent[]): LearningWindow {
  const modes = detectorLearning(definition, components);
  if (modes.length && modes.every((mode) => mode === "none")) return "none";
  return modes.some((mode) => mode !== "batch") ? "continuous" : "fitted";
}

/** Whether some detector is fitted once on the training window. */
export const hasFittedDetector = (definition: PipelineDefinition, components: PipelineComponent[]) =>
  detectorLearning(definition, components).includes("batch");

/** The detectors a node's output reaches, the node itself included. */
function detectorsFrom(definition: PipelineDefinition, nodeId: string) {
  const seen = new Set([nodeId]);
  for (const pending = [nodeId]; pending.length; ) {
    const current = pending.pop()!;
    for (const edge of definition.edges)
      if (edge.source === current && !seen.has(edge.target)) {
        seen.add(edge.target);
        pending.push(edge.target);
      }
  }
  return definition.nodes.filter((node) => node.kind === "detector" && seen.has(node.id));
}

/** Why a learned step does not belong before a node: a detector reads only steps that
 * learn as it does, and a pretrained one or one that follows a rule reads none that learn.
 * Undefined when it fits. */
export function learningBlocker(
  definition: PipelineDefinition,
  target: string,
  component: PipelineComponent,
  components: PipelineComponent[],
): string | undefined {
  const mode = component.learning ?? "none";
  if (mode === "none" || component.kind === "detector") return;
  const other = detectorsFrom(definition, target).map((node) => learningOf(node, components)).find((item) => item !== mode);
  if (!other) return;
  return other === "pretrained" ? "The detector here is pretrained and reads only steps that do not learn."
    : other === "none" ? "The detector here follows a rule and reads only steps that do not learn."
    : other === "batch" ? "Learns continuously, and the detector here is fitted once."
      : "Fitted once, and the detector here learns continuously.";
}

/** Learned steps and models that do the same job fitted once and learning continuously. */
const COUNTERPARTS: [fitted: string, continuous: string][] = [
  ["static.standard_scaler", "adaptive.standard_scaler"],
  ["static.min_max_scaler", "adaptive.min_max_scaler"],
  ["static.robust_scaler", "adaptive.robust_scaler"],
  ["static.pca", "adaptive.uncentered_pca"],
  ["static.random_projection", "adaptive.random_projection"],
];

function counterpart(node: PipelineNode, mode: Learning, components: PipelineComponent[]) {
  const pair = COUNTERPARTS.find((item) => item.includes(node.component));
  const wanted = pair?.[mode === "batch" ? 0 : 1];
  return components.find((component) => component.id === wanted && component.kind === node.kind && component.learning === mode);
}

/** The policy that fits the calibration step and the detectors. The fixed split gives
 * exact p-values, which the conformal alarm policy needs from detectors that have stopped
 * learning; with a detector that takes in every observation it gives a frozen score
 * threshold. A calibration step that keeps adapting sets a boundary to exceed. */
export function fittingPolicy(definition: PipelineDefinition, components: PipelineComponent[]) {
  const calibration = definition.nodes.find((node) => node.kind === "calibration");
  const modes = detectorLearning(definition, components);
  if (!calibration || !modes.length) return undefined;
  if (calibration.component !== FIXED_SPLIT) return "policy.exceedance";
  return modes.every((mode) => mode === "batch") ? "policy.martingale" : "policy.quantile";
}

const replaced = (node: PipelineNode, component: PipelineComponent, params = fieldDefaults(component.fields)): PipelineNode => ({
  ...node,
  component: component.id,
  contract_version: component.contract_version ?? 1,
  params,
});

/** The settings both versions of a step share keep their values. */
function sharedParams(node: PipelineNode, component: PipelineComponent) {
  const params = fieldDefaults(component.fields);
  for (const field of component.fields)
    if (field.name in node.params) params[field.name] = structuredClone(node.params[field.name]!);
  return params;
}

export type LearningChange = {
  definition: PipelineDefinition;
  /** Learned steps moved to the counterpart that learns as the detector now does. */
  converted: string[];
  /** The policy the design has now, when it had to change. */
  policy?: PipelineComponent;
};

/** Give the design the policy that fits it, when it has another one. */
export function fitPolicy(definition: PipelineDefinition, components: PipelineComponent[]): LearningChange {
  const policy = definition.nodes.find((node) => node.kind === "policy");
  const fitting = components.find((component) => component.id === fittingPolicy(definition, components) && component.kind === "policy");
  if (!policy || !fitting || policy.component === fitting.id) return { definition, converted: [] };
  return {
    definition: { ...definition, nodes: definition.nodes.map((node) => (node === policy ? replaced(node, fitting) : node)) },
    converted: [],
    policy: fitting,
  };
}

/** Change a detector's model. Its settings start from the new model's defaults and its
 * connections stay. When the new model learns differently, the learned steps that feed
 * only detectors of that kind move to their counterparts, and the policy follows. */
export function changeDetector(
  definition: PipelineDefinition,
  nodeId: string,
  component: PipelineComponent,
  components: PipelineComponent[],
): LearningChange {
  const mode = component.learning ?? "none";
  const swapped = { ...definition, nodes: definition.nodes.map((node) => (node.id === nodeId ? replaced(node, component) : node)) };
  const converted: string[] = [];
  const nodes = swapped.nodes.map((node) => {
    const own = learningOf(node, components);
    if (node.kind === "detector" || own === "none" || own === mode) return node;
    const readers = detectorsFrom(swapped, node.id);
    if (!readers.some((reader) => reader.id === nodeId)
      || readers.some((reader) => learningOf(reader, components) !== mode)) return node;
    const other = counterpart(node, mode, components);
    if (!other) return node;
    converted.push(node.id);
    return replaced(node, other, sharedParams(node, other));
  });
  const fitted = fitPolicy({ ...swapped, nodes }, components);
  return { ...fitted, converted };
}

/** Change the calibration method. How it combines detectors and its alarm rate stay
 * where the new method has them, and the policy follows. */
export function changeCalibration(
  definition: PipelineDefinition,
  nodeId: string,
  component: PipelineComponent,
  components: PipelineComponent[],
): LearningChange {
  const nodes = definition.nodes.map((node) => {
    if (node.id !== nodeId) return node;
    const params = fieldDefaults(component.fields);
    for (const name of ["fusion", "alpha"])
      if (name in node.params && component.fields.some((field) => field.name === name))
        params[name] = structuredClone(node.params[name]!);
    return replaced(node, component, params);
  });
  return fitPolicy({ ...definition, nodes }, components);
}

/** What a change did besides the step itself, in one sentence for a status line. */
export function changeNotice(change: LearningChange, mode: Learning | undefined) {
  const kind = mode === "batch" ? "fitted-once" : "continuous";
  const moved = change.converted.length;
  return [
    moved === 1 ? `1 learned step moved to its ${kind} counterpart.`
      : moved ? `${moved} learned steps moved to their ${kind} counterparts.` : "",
    change.policy ? `The detection rule is now ${change.policy.label}.` : "",
    moved || change.policy ? "Undo reverses this." : "",
  ].filter(Boolean).join(" ");
}

const COVERAGE: Record<NonNullable<PipelineComponent["coverage"]>, { label: string; help: string }> = {
  exchangeable: {
    label: "Exact while data stays alike",
    help: "Holds as long as new observations behave like the calibration window.",
  },
  long_run: {
    label: "Long-run alarm rate",
    help: "Over a long run the share of scores above the boundary approaches the alarm rate, also when the data drifts.",
  },
  none: {
    label: "No guarantee",
    help: "The boundary follows a model of the scores. Nothing guarantees how often scores cross it.",
  },
};

/** What a calibration method promises about its alarm rate, for its card and settings. */
export const coverage = (component: PipelineComponent | undefined) =>
  component?.coverage ? COVERAGE[component.coverage] : undefined;

const FAMILIES: Record<NonNullable<PipelineComponent["family"]>, string> = {
  conformal: "Conformal",
  bayesian: "Bayesian",
};
export const calibrationFamily = (component: PipelineComponent) =>
  component.family ? FAMILIES[component.family] : "Other";
