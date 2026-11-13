import type { PipelineComponent, PipelineNode } from "./contracts";
import {
  addBlocker, addComponent, collides, connectionIssue, connectNodes, lastNode, PLACEMENT_GAP, setNodeLabel, snap, stepTitle,
  type GraphDocument,
} from "./model";
import { combinedName, formulaName } from "./scope";
import { NODE_SIZE, nodePosition, switchedOff } from "./semantics";
import { switchOff } from "./stepSwitch";

/** Steps of a design with the connections among them, as they travel on the clipboard. */
export type StepFragment = {
  /** Tells the text on the clipboard apart from any other. */
  format: "aberration-steps";
  schema_version: 1;
  /** Each step with its place relative to the upper left corner of the group. */
  steps: Array<{ component: string; params: PipelineNode["params"]; label?: string; x: number; y: number;
    /** The step is switched off, and arrives switched off. */
    off?: true }>;
  /** Connections among the steps, by their place in the list. */
  links: Array<[number, number]>;
};

type Point = { x: number; y: number };

/** The chosen steps as a fragment, in the order the design lists them; undefined when none of them exists. */
export function copySteps(document: GraphDocument, ids: Iterable<string>): StepFragment | undefined {
  const chosen = new Set(ids);
  const picked = document.definition.nodes.flatMap((node, index) =>
    chosen.has(node.id) ? [{ node, at: nodePosition(document.layout, node.id, index) }] : []);
  if (!picked.length) return undefined;
  const corner = groupCorner(picked.map((item) => item.at));
  const place = new Map(picked.map((item, index) => [item.node.id, index]));
  return {
    format: "aberration-steps", schema_version: 1,
    steps: picked.map(({ node, at }) => {
      const label = stepTitle(node);
      // A step that is switched off travels as what it was.
      const was = switchedOff(document.layout, node);
      return { component: was?.component ?? node.component,
        params: structuredClone((was?.params ?? node.params) as PipelineNode["params"]),
        ...(label ? { label } : {}), ...(was ? { off: true as const } : {}),
        x: at.x - corner.x, y: at.y - corner.y };
    }),
    // In the order a step takes its inputs, so a combining step receives them as before.
    links: [...document.definition.edges].sort((a, b) => a.order - b.order).flatMap((edge): Array<[number, number]> => {
      const [from, to] = [place.get(edge.source), place.get(edge.target)];
      return from === undefined || to === undefined ? [] : [[from, to]];
    }),
  };
}

const groupCorner = (points: Point[]) => ({ x: Math.min(...points.map((point) => point.x)), y: Math.min(...points.map((point) => point.y)) });

export type Pasted = {
  document: GraphDocument;
  /** The steps that were added, in the order of the fragment. */
  ids: string[];
  /** Why a step was left out, once per reason. */
  skipped: string[];
};

/** The first place at a point, or below it, where the steps of a fragment cover no step of the design. */
function freePlace(document: GraphDocument, fragment: StepFragment, at: Point): Point {
  const boxes = document.definition.nodes.map((node, index) => nodePosition(document.layout, node.id, index));
  const left = snap(at.x);
  let top = snap(at.y);
  for (let attempt = 0; attempt < 64 && fragment.steps.some((step) => collides(boxes, left + step.x, top + step.y)); attempt++)
    top = snap(top + NODE_SIZE.height + PLACEMENT_GAP.y);
  return { x: left, y: top };
}

/** Add the steps of a fragment with their upper left corner at a place, or on the first free rows
 * below it, and connect them as they were.
 *
 * A step the design cannot take is left out with its reason: a second Input, a detector beside the
 * one it has, or a step past the limit. A connection is kept where both of its ends arrived.
 */
export function pasteSteps(document: GraphDocument, fragment: StepFragment, components: PipelineComponent[], near: Point): Pasted {
  const at = freePlace(document, fragment, near);
  let next = document;
  const skipped = new Set<string>();
  const titles = new Set(document.definition.nodes.map((node) => stepTitle(node)).filter(Boolean));
  const added = fragment.steps.map((step) => {
    const component = components.find((item) => item.id === step.component);
    const blocker = component ? addBlocker(next.definition, component) : "This design does not offer one of the steps.";
    if (!component || blocker) { skipped.add(blocker!); return undefined; }
    const placed = addComponent(next, component, { x: snap(at.x + step.x), y: snap(at.y + step.y) }, undefined, step.params);
    const id = lastNode(placed);
    // A title of its own comes along, and says that it is a copy where the design has that title already.
    next = step.label ? setNodeLabel(placed, id, titles.has(step.label) ? `${step.label} copy` : step.label) : placed;
    if (step.off) next = switchOff(next, [id], components);
    return id;
  });
  for (const [from, to] of fragment.links) {
    const [source, target] = [added[from], added[to]];
    if (source && target && !connectionIssue(next.definition, source, target, components))
      next = { ...next, definition: connectNodes(next.definition, source, target, components) };
  }
  next = followRenames(next, fragment, added, components);
  return { document: next, ids: added.flatMap((id) => id ?? []), skipped: [...skipped] };
}

/** A copied step that names a feature the design has already gets a name of its own; the copied steps
 * after it read the feature by that name, so the copy computes what the original does. */
function followRenames(document: GraphDocument, fragment: StepFragment, added: Array<string | undefined>,
  components: PipelineComponent[]): GraphDocument {
  const nodes = new Map(document.definition.nodes.map((node) => [node.id, node]));
  const component = (id: string) => components.find((item) => item.id === id);
  const renames = fragment.steps.flatMap((step, index) => {
    const node = added[index] ? nodes.get(added[index]!) : undefined;
    if (!node) return [];
    const was = combinedName({ ...node, params: step.params }, component(step.component));
    const now = combinedName(node, component(node.component));
    return was && now && was !== now ? [{ index, was, now }] : [];
  });
  if (!renames.length) return document;
  const after = (start: number) => {
    const reached = new Set<number>();
    const visit = (from: number) => fragment.links.forEach(([source, target]) => {
      if (source === from && !reached.has(target)) { reached.add(target); visit(target); }
    });
    visit(start);
    return reached;
  };
  const params = new Map<string, PipelineNode["params"]>();
  for (const { index, was, now } of renames) for (const target of after(index)) {
    const id = added[target];
    if (id) params.set(id, renameFeature(params.get(id) ?? nodes.get(id)!.params, was, now) as PipelineNode["params"]);
  }
  return { ...document, definition: { ...document.definition,
    nodes: document.definition.nodes.map((node) => params.has(node.id) ? { ...node, params: params.get(node.id)! } : node) } };
}

const escaped = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Settings with a feature read by another name: where a setting names it, where a mapping keys it,
 * and where an expression uses it, bare or between backticks. */
export function renameFeature(value: unknown, was: string, now: string, key?: string): unknown {
  if (typeof value === "string") {
    if (value === was) return now;
    if (key !== "expression") return value;
    return value.replace(new RegExp(`\`${escaped(was)}\`|(?<![\\w\`])${escaped(was)}(?![\\w\`])`, "g"), formulaName(now));
  }
  if (Array.isArray(value)) return value.map((item) => renameFeature(item, was, now, key));
  if (value && typeof value === "object")
    return Object.fromEntries(Object.entries(value).map(([name, item]) => [name === was ? now : name, renameFeature(item, was, now, name)]));
  return value;
}

/** Copies of the chosen steps under the group, on the first rows where they cover no other step. */
export function duplicateSteps(document: GraphDocument, ids: Iterable<string>, components: PipelineComponent[]): Pasted | undefined {
  const chosen = new Set(ids);
  const fragment = copySteps(document, chosen);
  if (!fragment) return undefined;
  const group = document.definition.nodes.flatMap((node, index) =>
    chosen.has(node.id) ? [nodePosition(document.layout, node.id, index)] : []);
  return pasteSteps(document, fragment, components, {
    x: groupCorner(group).x,
    y: Math.max(...group.map((box) => box.y)) + NODE_SIZE.height + PLACEMENT_GAP.y,
  });
}

/** How wide and high the steps of a fragment stand, to centre them on a place. */
export function fragmentSize(fragment: StepFragment) {
  return { width: Math.max(...fragment.steps.map((step) => step.x)) + NODE_SIZE.width,
    height: Math.max(...fragment.steps.map((step) => step.y)) + NODE_SIZE.height };
}

/** The steps in a text from the clipboard; undefined for any other text. */
export function readSteps(text: string): StepFragment | undefined {
  if (!text.includes('"aberration-steps"')) return undefined;
  try {
    const value: unknown = JSON.parse(text);
    if (typeof value !== "object" || value === null) return undefined;
    const { format, schema_version, steps, links } = value as Partial<StepFragment>;
    if (format !== "aberration-steps" || schema_version !== 1 || !Array.isArray(steps) || !steps.length || !Array.isArray(links)) return undefined;
    const sound = steps.every((step) => typeof step?.component === "string" && typeof step.params === "object" && step.params !== null
      && Number.isFinite(step.x) && Number.isFinite(step.y) && (step.label === undefined || typeof step.label === "string")
      && (step.off === undefined || step.off === true))
      && links.every((link) => Array.isArray(link) && link.length === 2 && link.every((end) => Number.isInteger(end) && end >= 0 && end < steps.length));
    return sound ? { format, schema_version, steps, links } : undefined;
  } catch {
    return undefined;
  }
}

/** What the last copy held, for a menu that cannot read the clipboard without asking. */
let held: StepFragment | undefined;
export const heldSteps = () => held;

/** Keep a fragment for Paste, and give its text for the clipboard. */
export function holdSteps(fragment: StepFragment) {
  held = fragment;
  return JSON.stringify(fragment);
}

/** "Pasted 2 steps." with what was left out and why. */
export function pastedNote(verb: string, result: Pick<Pasted, "ids" | "skipped">) {
  const count = result.ids.length;
  const done = count ? `${verb} ${count} step${count === 1 ? "" : "s"}.` : "Nothing was added.";
  return result.skipped.length ? `${done} Left out: ${result.skipped.join(" ")}` : done;
}
