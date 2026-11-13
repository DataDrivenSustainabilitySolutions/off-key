import type { PipelineComponent, PipelineDefinition, PipelineValidation } from "./contracts";
import { learningBlocker } from "./learning";
import { detectorIds, incomingEdges, insertOnEdge, type GraphDocument, type Link } from "./model";
import { stepFamily } from "./steps";

/** One feature the detector receives, with the steps that made it. */
export type FeatureRow = {
  /** The name the detector receives it under. */
  name: string;
  /** The steps that changed it, in the order they run. */
  steps: string[];
  /** The readings it comes from. */
  slots: string[];
  minimum?: number | null;
  maximum?: number | null;
  /** The reading it follows; an Aggregate's, a Formula's or a projection's feature follows none. */
  reading?: string;
};

export type FeaturesView = {
  /** The node that hands the detector its features. */
  last?: string;
  detector?: string;
  /** Every detector of the design, in RADAR's order; the view shows one of them. */
  detectors: string[];
  /** Features that follow a reading, by reading, then the ones made from several. */
  rows: FeatureRow[];
  /** Readings no feature the detector receives comes from. */
  unused: string[];
  /** Whether the check reported each feature's steps; large designs leave them out. */
  complete: boolean;
};

type Columns = PipelineValidation["features"];

/** Node ids hold no dots, so the first dot of node.name ends the node. */
function split(reference: string): [string, string] {
  const dot = reference.indexOf(".");
  return [reference.slice(0, dot), reference.slice(dot + 1)];
}

/** Where a feature was on its way to a node, from where it was made: [node, name] pairs. */
function featurePath(features: Columns, node: string, name: string): [string, string][] {
  const path: [string, string][] = [];
  const seen = new Set<string>();
  let current: [string, string] | undefined = [node, name];
  while (current && !seen.has(current.join("."))) {
    seen.add(current.join("."));
    path.push(current);
    const [id, feature]: [string, string] = current;
    const previous: string | null | undefined = features[id]?.find((column) => column.name === feature)?.previous;
    current = previous ? split(previous) : undefined;
  }
  return path.reverse();
}

/** The features a detector receives, the chosen one or else the first, computed from
 * the graph and its last check. */
export function featuresView(
  definition: PipelineDefinition,
  report?: Pick<PipelineValidation, "features" | "provenance_complete">,
  chosen?: string,
): FeaturesView {
  const detectors = detectorIds(definition);
  const detector = chosen && detectors.includes(chosen) ? chosen : detectors[0];
  const source = definition.nodes.find((node) => node.kind === "source")?.id;
  const last = detector ? incomingEdges(definition, detector)[0]?.source : undefined;
  const columns = (last && report?.features[last]) || [];
  const slots = definition.input_slots.map((slot) => slot.id);
  const rows = columns.map((column): FeatureRow => {
    const [origin, name] = featurePath(report?.features ?? {}, last!, column.name)[0]!;
    return {
      name: column.name,
      steps: column.steps ?? [],
      slots: column.slots,
      minimum: column.minimum,
      maximum: column.maximum,
      reading: origin === source && slots.includes(name) ? name : undefined,
    };
  });
  // Features that follow a reading stay with it, in reading order; the others follow.
  const order = (row: FeatureRow) => row.reading === undefined ? slots.length : slots.indexOf(row.reading);
  const sorted = rows.map((row, index) => ({ row, index }))
    .sort((left, right) => order(left.row) - order(right.row) || left.index - right.index)
    .map(({ row }) => row);
  const used = new Set(rows.flatMap((row) => row.slots));
  return {
    last,
    detector,
    detectors,
    rows: sorted,
    unused: last && report?.features[last] ? slots.filter((slot) => !used.has(slot)) : [],
    complete: report?.provenance_complete !== false,
  };
}

/** Steps that learn, and every node after one: Prepare steps cannot follow them. */
function learnedStage(definition: PipelineDefinition, components: PipelineComponent[]) {
  const memo = new Map<string, boolean>();
  const learned = (id: string): boolean => {
    const known = memo.get(id);
    if (known !== undefined) return known;
    // A cycle, which the editor refuses to draw, ends here.
    memo.set(id, false);
    const node = definition.nodes.find((item) => item.id === id);
    const family = node && stepFamily(node, components.find((component) => component.id === node.component));
    const result = family === "normalize" || family === "reduce"
      || incomingEdges(definition, id).some((edge) => learned(edge.source));
    memo.set(id, result);
    return result;
  };
  return learned;
}

/** Steps a feature's row offers: per-feature steps that can use one feature and, when
 * they learn, learn as the row's detector does. */
export function rowSteps(definition: PipelineDefinition, components: PipelineComponent[], detector?: string) {
  return components.filter((component) => {
    return (component.group === "prepare" || component.group === "normalize")
      && component.fields.some((field) => field.name === "apply_to")
      && !(detector && learningBlocker(definition, detector, component, components));
  });
}

export type RowPlacement = { link: Link; feature: string } | { reason: string };

/** Where a step for one feature goes, and the feature's name there. A learned step goes
 * just before the detector. A Prepare step goes before the first learned step on the
 * feature's way, which is the latest place it can run; the detector's input otherwise. */
export function rowPlacement(
  definition: PipelineDefinition,
  report: Pick<PipelineValidation, "features">,
  components: PipelineComponent[],
  view: FeaturesView,
  row: FeatureRow,
  component: PipelineComponent,
): RowPlacement {
  const { last, detector } = view;
  if (!last || !detector) return { reason: "Connect a detector first." };
  if (component.group !== "prepare")
    return { link: { source: last, target: detector }, feature: row.name };
  const path = featurePath(report.features, last, row.name);
  const learned = learnedStage(definition, components);
  const first = path.findIndex(([node]) => learned(node));
  if (first < 0) return { link: { source: last, target: detector }, feature: row.name };
  if (first === 0) return { reason: `${row.name} comes from a learned step, and Prepare steps run before anything learns.` };
  const [source, feature] = path[first - 1]!;
  return { link: { source, target: path[first]![0] }, feature };
}

/** The detectors downstream of a node, the node itself included when it is one. */
export function detectorsAfter(definition: PipelineDefinition, id: string) {
  const reached = new Set<string>();
  const pending = [id];
  while (pending.length) {
    const current = pending.pop()!;
    if (reached.has(current)) continue;
    reached.add(current);
    pending.push(...definition.edges.filter((edge) => edge.source === current).map((edge) => edge.target));
  }
  return detectorIds(definition).filter((detector) => reached.has(detector));
}

/** Insert a step that uses only the row's feature, set to that feature. */
export function addForFeature(
  document: GraphDocument,
  report: Pick<PipelineValidation, "features">,
  components: PipelineComponent[],
  view: FeaturesView,
  row: FeatureRow,
  component: PipelineComponent,
): { document: GraphDocument; id: string } | undefined {
  const placement = rowPlacement(document.definition, report, components, view, row, component);
  if ("reason" in placement) return;
  const inserted = insertOnEdge(document, placement.link, component, components);
  if (!inserted) return;
  const definition = inserted.document.definition;
  return {
    id: inserted.id,
    document: {
      ...inserted.document,
      definition: {
        ...definition,
        nodes: definition.nodes.map((node) => node.id === inserted.id
          ? { ...node, params: { ...node.params, apply_to: [placement.feature] } }
          : node),
      },
    },
  };
}

const amount = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 4 });
/** The check writes "above 0" as the smallest positive number, as for the seconds between
 * observations, and what is computed from it can stay as close to 0. Written out it would
 * be hundreds of zeros, so an end this close to 0 reads as the side of 0 it is on. */
const NEAR_ZERO = 1e-9;
function known(value: number | null | undefined, end: "low" | "high") {
  if (typeof value !== "number" || !Number.isFinite(value)) return undefined;
  if (value === 0 || Math.abs(value) >= NEAR_ZERO) return amount.format(value);
  return end === "low" ? value > 0 ? "above 0" : "0" : value < 0 ? "below 0" : "0";
}

/** A feature's range as the check inferred it: "0 to 1,200", "at least 0", "above 0", or
 * nothing when unbounded. */
export function rangeText(minimum?: number | null, maximum?: number | null) {
  const low = known(minimum, "low");
  const high = known(maximum, "high");
  if (low !== undefined && high !== undefined) return low === high ? `always ${low}` : `${low} to ${high}`;
  if (low !== undefined) return low === "above 0" ? low : `at least ${low}`;
  if (high !== undefined) return high === "below 0" ? high : `at most ${high}`;
}

/** Whether a Gate can hold observations back before a step reaches it: the step is a
 * Gate, or one runs before it. */
export function afterGate(definition: PipelineDefinition, id: string) {
  const seen = new Set<string>();
  const pending = [id];
  while (pending.length) {
    const current = pending.pop()!;
    if (seen.has(current)) continue;
    seen.add(current);
    if (definition.nodes.find((node) => node.id === current)?.component === "prepare.gate") return true;
    pending.push(...incomingEdges(definition, current).map((edge) => edge.source));
  }
  return false;
}

/** When a Prepare step gives its first output, as the check counted it. */
export function readyText(observation: number, gated: boolean) {
  if (observation <= 1)
    return gated ? "Ready from the first observation a Gate lets through" : "Ready from the first observation";
  return `Ready after ${gated ? "at least " : ""}${observation.toLocaleString()} observations`;
}

/** Why the features arriving at a step are unknown: the nearest step before it whose
 * error stops the check from working out its features. Undefined while they are known. */
export function featureBlocker(
  definition: PipelineDefinition,
  validation: Pick<PipelineValidation, "features" | "issues"> | undefined,
  target: string,
): { node?: string; issue?: PipelineValidation["issues"][number] } | undefined {
  const sources = incomingEdges(definition, target).map((edge) => edge.source);
  if (!validation || !sources.length) return undefined;
  const known = (id: string) => validation.features[id] !== undefined;
  if (sources.every(known)) return undefined;
  const error = (id: string) => validation.issues.find((issue) => issue.node_id === id && issue.severity !== "warning");
  const seen = new Set<string>();
  const queue = sources.filter((id) => !known(id));
  let fallback: { node: string; issue: PipelineValidation["issues"][number] } | undefined;
  while (queue.length) {
    const id = queue.shift()!;
    if (seen.has(id)) continue;
    seen.add(id);
    const parents = incomingEdges(definition, id).map((edge) => edge.source);
    const issue = error(id);
    // The step whose own inputs are known is where the features stop.
    if (issue && parents.every(known)) return { node: id, issue };
    if (issue) fallback ??= { node: id, issue };
    queue.push(...parents.filter((parent) => !known(parent)));
  }
  return fallback ?? {};
}
