import { PIPELINE_LIMITS } from "@/types/pipelines.generated";
import { fieldDefaults } from "@/components/parameter-editor/types";
import type {
  PipelineDefinition,
  PipelineEdge,
  PipelineLayout,
  PipelineNode,
  PipelineComponent,
} from "./contracts";
import { learningBlocker } from "./learning";
import { combinedName } from "./scope";
import {
  componentFor,
  edgeId,
  dataKinds,
  GRID_STEP,
  inputKind,
  takes,
  NODE_SIZE,
  nodePosition,
  outputKind,
} from "./semantics";

export { PIPELINE_LIMITS };

/** Transforms and merges may repeat; a design combines up to four detectors through
 * Add another detector; every other kind appears once per design. */
export const isMultiInstanceKind = (kind: string) => kind === "transform" || kind === "merge";

/** A node's inputs in merge order. */
export const incomingEdges = (definition: PipelineDefinition, nodeId: string) =>
  definition.edges.filter((edge) => edge.target === nodeId).sort((left, right) => left.order - right.order);

/** The detectors in the order RADAR combines and reports them: by node id. */
export const detectorIds = (definition: PipelineDefinition) =>
  definition.nodes.filter((node) => node.kind === "detector").map((node) => node.id)
    .sort((left, right) => (left < right ? -1 : left > right ? 1 : 0));

/** Nodes that take several inputs: a merge in order, the calibration step one per detector. */
const takesSeveral = (definition: PipelineDefinition, nodeId: string) => {
  const kind = definition.nodes.find((node) => node.id === nodeId)?.kind;
  return kind === "merge" || kind === "calibration";
};

export type GraphDocument = {
  definition: PipelineDefinition;
  layout: PipelineLayout;
};

export function nodeLabel(
  node: PipelineNode | undefined,
  components: PipelineComponent[],
  layout?: PipelineLayout,
): string {
  if (!node) return "Missing component";
  return (
    layout?.nodes[node.id]?.label ||
    components.find((item) => item.id === node.component)?.label ||
    node.component
  );
}

/** Option labels that add the node ID where several nodes share a label. Labels
 * are counted once per document instead of once per labelled node. */
export function nodeOptionLabeler(
  document: GraphDocument,
  components: PipelineComponent[],
): (node: PipelineNode | undefined) => string {
  const counts = new Map<string, number>();
  for (const item of document.definition.nodes) {
    const label = nodeLabel(item, components, document.layout);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return (node) => {
    const label = nodeLabel(node, components, document.layout);
    return node && (counts.get(label) ?? 0) > 1 ? `${label} · ${node.id}` : label;
  };
}

/** Node IDs and slot IDs are stable; displayed labels never enter connections. */
function nextNodeId(nodes: PipelineNode[], component: string): string {
  const prefix = component.replace(/[^a-zA-Z0-9_-]/g, "_");
  let suffix = 1;
  while (nodes.some((node) => node.id === `${prefix}_${suffix}`)) suffix++;
  return `${prefix}_${suffix}`;
}

/** Defaults for a new step. A second Formula or Aggregate that would compute a feature
 * an earlier one already computes gets its own name, such as formula_2 or mean_2. */
function newParams(
  nodes: PipelineNode[], component: PipelineComponent, params: PipelineNode["params"] = fieldDefaults(component.fields),
): PipelineNode["params"] {
  if (component.id !== "prepare.formula" && component.id !== "prepare.aggregate") return params;
  const taken = new Set(nodes.map((node) => combinedName(node, componentFor(node, [component]))).filter(Boolean));
  const base = combinedName({ id: "", kind: component.kind, component: component.id, params }, component)!;
  if (!taken.has(base)) return params;
  let index = 2;
  while (taken.has(`${base}_${index}`)) index++;
  return { ...params, name: `${base}_${index}` };
}

export function addComponent(
  document: GraphDocument,
  component: PipelineComponent,
  position?: { x: number; y: number },
  anchor?: string,
  /** Settings to start from instead of the defaults, as a duplicate does. */
  initial?: PipelineNode["params"],
): GraphDocument {
  if (addBlocker(document.definition, component)) return document;
  const id = nextNodeId(document.definition.nodes, component.id);
  const instance =
    document.definition.nodes.filter((node) => node.component === component.id)
      .length + 1;
  const params = newParams(document.definition.nodes, component, initial && structuredClone(initial));
  return {
    definition: {
      ...document.definition,
      nodes: [
        ...document.definition.nodes,
        {
          id,
          kind: component.kind,
          component: component.id,
          contract_version: component.contract_version ?? 1,
          params,
        },
      ],
    },
    layout: {
      ...document.layout,
      nodes: {
        ...document.layout.nodes,
        [id]: {
          ...(position ?? freePosition(document, anchor)),
          ...(instance > 1 ? { label: `${component.label} ${instance}` } : {}),
        },
      },
    },
  };
}

const PLACEMENT_GAP = { x: 64, y: 32 };
const snap = (value: number) => Math.round(value / GRID_STEP) * GRID_STEP;

/** Whether a card at x, y would touch any box, including half a placement gap around it. */
const collides = (boxes: { x: number; y: number }[], x: number, y: number) =>
  boxes.some(
    (box) =>
      box.x < x + NODE_SIZE.width + PLACEMENT_GAP.x / 2 &&
      x < box.x + NODE_SIZE.width + PLACEMENT_GAP.x / 2 &&
      box.y < y + NODE_SIZE.height + PLACEMENT_GAP.y / 2 &&
      y < box.y + NODE_SIZE.height + PLACEMENT_GAP.y / 2,
  );

/** The first free row at x, moving down from y. */
function freeRow(boxes: { x: number; y: number }[], x: number, y: number) {
  let top = y;
  for (let attempt = 0; attempt < 64 && collides(boxes, x, top); attempt++)
    top = snap(top + NODE_SIZE.height + PLACEMENT_GAP.y);
  return top;
}

/** Place to the right of the anchor (or the rightmost component) without covering another box. */
export function freePosition(document: GraphDocument, anchor?: string) {
  const boxes = document.definition.nodes.map((node, index) =>
    nodePosition(document.layout, node.id, index),
  );
  if (!boxes.length) return { x: 0, y: 0 };
  const anchorIndex = document.definition.nodes.findIndex((node) => node.id === anchor);
  const from =
    anchorIndex >= 0
      ? boxes[anchorIndex]!
      : boxes.reduce((right, box) => (box.x > right.x ? box : right));
  const x = snap(from.x + NODE_SIZE.width + PLACEMENT_GAP.x);
  return { x, y: freeRow(boxes, x, snap(from.y)) };
}

/** Current V1 execution profile, shared by drag/drop and the component palette. */
export function addBlocker(
  definition: PipelineDefinition,
  component: PipelineComponent,
): string | undefined {
  if (component.unavailable) return component.unavailable;
  if (definition.nodes.length >= PIPELINE_LIMITS.nodes)
    return `The design has reached its ${PIPELINE_LIMITS.nodes}-component limit.`;
  if (component.kind === "detector" && detectorIds(definition).length)
    return detectorIds(definition).length >= PIPELINE_LIMITS.detectors
      ? `A design combines at most ${PIPELINE_LIMITS.detectors} detectors.`
      : "Add another detector from a detector's settings.";
  if (
    !isMultiInstanceKind(component.kind) &&
    definition.nodes.some((node) => node.kind === component.kind)
  )
    return "A design has one of these.";
}

/** Why Add another detector is unavailable; undefined when it can add one. */
export function detectorBlocker(definition: PipelineDefinition): string | undefined {
  if (detectorIds(definition).length >= PIPELINE_LIMITS.detectors)
    return `A design combines at most ${PIPELINE_LIMITS.detectors} detectors.`;
  if (definition.nodes.length >= PIPELINE_LIMITS.nodes)
    return `The design has reached its ${PIPELINE_LIMITS.nodes}-component limit.`;
  if (definition.edges.length + 2 > PIPELINE_LIMITS.edges)
    return `The design has reached its ${PIPELINE_LIMITS.edges}-connection limit.`;
}

/** Another detector like this one: the same model and settings, reading the same
 * input and connected to the calibration step, placed below it. Its model and input can then be
 * changed like any step's. */
export function addDetector(
  document: GraphDocument,
  detectorId: string,
): { document: GraphDocument; id: string } | undefined {
  const { definition, layout } = document;
  const original = definition.nodes.find((node) => node.id === detectorId && node.kind === "detector");
  if (!original || detectorBlocker(definition)) return;
  let suffix = 2;
  while (definition.nodes.some((node) => node.id === `detector_${suffix}`)) suffix++;
  const id = `detector_${suffix}`;
  const input = incomingEdges(definition, detectorId)[0];
  const calibration = definition.nodes.find((node) => node.kind === "calibration");
  const boxes = definition.nodes.map((node, index) => nodePosition(layout, node.id, index));
  const anchor = boxes[definition.nodes.indexOf(original)]!;
  return {
    id,
    document: {
      definition: {
        ...definition,
        nodes: [...definition.nodes, { ...structuredClone(original), id }],
        edges: [
          ...definition.edges,
          ...(input ? [{ source: input.source, target: id, order: 0 }] : []),
          ...(calibration ? [{ source: id, target: calibration.id, order: incomingEdges(definition, calibration.id).length }] : []),
        ],
      },
      layout: {
        ...layout,
        nodes: { ...layout.nodes, [id]: { x: anchor.x, y: freeRow(boxes, anchor.x, snap(anchor.y)) } },
      },
    },
  };
}

/** Remove nodes with every incident edge and their layout, plus any listed edges; merge order is kept. */
export function removeElements(
  document: GraphDocument,
  { nodeIds = [], edgeIds = [] }: { nodeIds?: string[]; edgeIds?: string[] },
): GraphDocument {
  const nodes = new Set(nodeIds);
  const edges = new Set(edgeIds);
  return {
    definition: {
      ...document.definition,
      nodes: document.definition.nodes.filter((node) => !nodes.has(node.id)),
      edges: document.definition.edges.filter(
        (edge) => !nodes.has(edge.source) && !nodes.has(edge.target) && !edges.has(edgeId(edge)),
      ),
    },
    layout: {
      ...document.layout,
      nodes: Object.fromEntries(Object.entries(document.layout.nodes).filter(([id]) => !nodes.has(id))),
    },
  };
}

export const removeNode = (document: GraphDocument, id: string) => removeElements(document, { nodeIds: [id] });

/** Remove every connection into and out of a node; the node stays in place. */
export const disconnectNode = (document: GraphDocument, id: string): GraphDocument => ({
  ...document,
  definition: {
    ...document.definition,
    edges: document.definition.edges.filter((edge) => edge.source !== id && edge.target !== id),
  },
});

/** The step most recently added to a document. */
const lastNode = (document: GraphDocument) => document.definition.nodes[document.definition.nodes.length - 1]!.id;

/** Copy a step with its settings below the original, unconnected. One-per-design steps
 * and detectors are not copied; undefined says it cannot be. */
export function duplicateNode(
  document: GraphDocument,
  nodeId: string,
  components: PipelineComponent[],
): { document: GraphDocument; id: string } | undefined {
  const index = document.definition.nodes.findIndex((node) => node.id === nodeId);
  const node = document.definition.nodes[index];
  const component = componentFor(node, components);
  if (!node || !component || duplicateBlocker(document.definition, nodeId, components)) return;
  const boxes = document.definition.nodes.map((item, position) => nodePosition(document.layout, item.id, position));
  const from = boxes[index]!;
  const position = { x: from.x, y: freeRow(boxes, from.x, snap(from.y + NODE_SIZE.height + PLACEMENT_GAP.y)) };
  const added = addComponent(document, component, position, undefined, node.params);
  const id = lastNode(added);
  const label = document.layout.nodes[nodeId]?.label;
  return { id, document: label ? setNodeLabel(added, id, `${label} copy`) : added };
}

/** Why a step cannot be duplicated; undefined when it can. */
export function duplicateBlocker(
  definition: PipelineDefinition,
  nodeId: string,
  components: PipelineComponent[],
): string | undefined {
  const node = definition.nodes.find((item) => item.id === nodeId);
  const component = componentFor(node, components);
  if (!node || !component) return "Compatible component metadata is required before copying this step.";
  if (node.kind === "detector") return "Add another detector from a detector's settings.";
  return addBlocker(definition, component);
}

/** Add a step that takes a node's output. When the node has one connection out and the
 * step fits on it, the step goes in between, so a chain stays a chain; otherwise the
 * step starts a new branch beside the node. */
export function addAfter(
  document: GraphDocument,
  nodeId: string,
  component: PipelineComponent,
  components: PipelineComponent[],
): { document: GraphDocument; id: string } | undefined {
  const outgoing = document.definition.edges.filter((edge) => edge.source === nodeId);
  if (outgoing.length === 1) {
    const inserted = insertOnEdge(document, outgoing[0]!, component, components);
    if (inserted) return inserted;
  }
  if (addBlocker(document.definition, component)) return;
  const added = addComponent(document, component, undefined, nodeId);
  const id = lastNode(added);
  if (connectionIssue(added.definition, nodeId, id, components)) return;
  return { id, document: { ...added, definition: connectNodes(added.definition, nodeId, id, components) } };
}

/** Why a step cannot follow a node; undefined when Add after can place it. */
export function afterBlocker(
  document: GraphDocument,
  nodeId: string,
  component: PipelineComponent,
  components: PipelineComponent[],
): string | undefined {
  if (addAfter(document, nodeId, component, components)) return;
  return addBlocker(document.definition, component) ?? "Does not take this step's output.";
}

export const disconnectEdge = (definition: PipelineDefinition, edge: Pick<PipelineEdge, "source" | "target">): PipelineDefinition => ({
  ...definition,
  edges: definition.edges.filter((item) => edgeId(item) !== edgeId(edge)),
});

const updateNode = (document: GraphDocument, nodeId: string, change: (node: PipelineNode) => PipelineNode): GraphDocument => ({
  ...document,
  definition: {
    ...document.definition,
    nodes: document.definition.nodes.map((node) => (node.id === nodeId ? change(node) : node)),
  },
});

/** Swap a node's component; its parameters reset to the catalogue defaults and its connections stay. */
export const replaceComponent = (document: GraphDocument, nodeId: string, component: PipelineComponent) =>
  updateNode(document, nodeId, (node) => ({
    ...node,
    component: component.id,
    contract_version: component.contract_version ?? 1,
    params: fieldDefaults(component.fields),
  }));

export const setNodeParams = (document: GraphDocument, nodeId: string, params: PipelineNode["params"]) =>
  updateNode(document, nodeId, (node) => ({ ...node, params }));

/** Title a node; a node without a stored position gets its default one. */
export function setNodeLabel(document: GraphDocument, nodeId: string, label: string): GraphDocument {
  const index = document.definition.nodes.findIndex((node) => node.id === nodeId);
  return {
    ...document,
    layout: {
      ...document.layout,
      nodes: {
        ...document.layout.nodes,
        [nodeId]: { ...nodePosition(document.layout, nodeId, index), ...document.layout.nodes[nodeId], label },
      },
    },
  };
}

/** `replace` lets a new connection take over a single input that is already connected. */
type ConnectOptions = { replace?: boolean };

/** The connection into a single input, which a new connection to it would replace. */
export const occupiedInput = (definition: PipelineDefinition, target: string) =>
  takesSeveral(definition, target)
    ? undefined
    : definition.edges.find((edge) => edge.target === target);

/** Authoring guard shared by the canvas and keyboard/menu connection editor.
 * The backend compiler remains authoritative for publication and activation.
 */
export function connectionIssue(
  definition: PipelineDefinition,
  source: string,
  target: string,
  components: PipelineComponent[],
  { replace = false }: ConnectOptions = {},
): string | undefined {
  const from = definition.nodes.find((node) => node.id === source);
  const to = definition.nodes.find((node) => node.id === target);
  if (!from || !to) return "Choose two existing components.";
  if (source === target) return "A component cannot connect to itself.";
  if (
    definition.edges.some(
      (edge) => edge.source === source && edge.target === target,
    )
  )
    return "This connection is already present.";
  const replaced = replace ? occupiedInput(definition, target) : undefined;
  if (definition.edges.length - (replaced ? 1 : 0) >= PIPELINE_LIMITS.edges)
    return `The design has reached its ${PIPELINE_LIMITS.edges}-connection limit.`;
  const fromComponent = componentFor(from, components);
  const toComponent = componentFor(to, components);
  if (!fromComponent || !toComponent)
    return "Compatible component metadata is required before connecting these nodes.";
  const output = outputKind(from, fromComponent);
  const input = inputKind(toComponent);
  if (!output) return "Evidence output is terminal.";
  if (!input) return "Aligned inputs have no incoming port.";
  if (!takes(toComponent, output))
    return `Cannot connect ${dataKinds[output].label} to ${dataKinds[input].label}.`;
  if (!replace && occupiedInput(definition, target))
    return "This input is occupied. Disconnect it before choosing a replacement.";
  const reachable = new Set([target]);
  for (let changed = true; changed; ) {
    changed = false;
    for (const edge of definition.edges)
      if (reachable.has(edge.source) && !reachable.has(edge.target)) {
        reachable.add(edge.target);
        changed = true;
      }
  }
  if (reachable.has(source)) return "This connection would create a cycle.";
}

export function connectNodes(
  definition: PipelineDefinition,
  source: string,
  target: string,
  components: PipelineComponent[],
  options: ConnectOptions = {},
): PipelineDefinition {
  if (connectionIssue(definition, source, target, components, options))
    return definition;
  // A merge or the calibration step appends the new input; a single input keeps only the new one.
  const incoming = takesSeveral(definition, target) ? incomingEdges(definition, target) : [];
  return {
    ...definition,
    edges: [
      ...definition.edges.filter((edge) => edge.target !== target),
      ...incoming.map((edge, order) => ({ ...edge, order })),
      { source, target, order: incoming.length },
    ],
  };
}

/** A connection by its ends; V1 allows one per pair. */
export type Link = Pick<PipelineEdge, "source" | "target">;

/** Why a component cannot be placed on a connection; undefined when it fits. */
export function insertBlocker(
  definition: PipelineDefinition,
  link: Link,
  component: PipelineComponent,
  components: PipelineComponent[],
): string | undefined {
  const blocker = addBlocker(definition, component);
  if (blocker) return blocker;
  // The link is replaced by two, so the design needs room for one more.
  if (definition.edges.length >= PIPELINE_LIMITS.edges)
    return `The design has reached its ${PIPELINE_LIMITS.edges}-connection limit.`;
  const from = definition.nodes.find((node) => node.id === link.source);
  const to = definition.nodes.find((node) => node.id === link.target);
  const fromComponent = componentFor(from, components);
  const toComponent = componentFor(to, components);
  if (!from || !fromComponent || !toComponent)
    return "Compatible component metadata is required before inserting here.";
  const carried = outputKind(from, fromComponent);
  const produces = component.kind === "output" ? undefined : (component.output_type ?? "features");
  if (!carried || !takes(component, carried) || !takes(toComponent, produces))
    return `Does not fit a connection that carries ${dataKinds[carried ?? "features"].label.toLowerCase()}.`;
  return learningBlocker(definition, link.target, component, components);
}

/** Room for a card on a link: between its ends when there is space, otherwise a
 * column opened at the target by moving it and everything to its right. */
function roomOnLink(document: GraphDocument, link: Link) {
  const { definition, layout } = document;
  const boxes = definition.nodes.map((node, index) => ({
    id: node.id, ...nodePosition(layout, node.id, index),
  }));
  const source = boxes.find((box) => box.id === link.source)!;
  const target = boxes.find((box) => box.id === link.target)!;
  const gap = target.x - (source.x + NODE_SIZE.width);
  if (gap >= NODE_SIZE.width + PLACEMENT_GAP.x) {
    const x = snap(source.x + NODE_SIZE.width + (gap - NODE_SIZE.width) / 2);
    const y = snap((source.y + target.y) / 2);
    if (!collides(boxes, x, y)) return { layout, position: { x, y } };
  }
  if (target.x <= source.x) return { layout, position: freePosition(document, link.source) };
  const shift = snap(NODE_SIZE.width + PLACEMENT_GAP.x);
  const moved = boxes.map((box) => (box.x >= target.x ? { ...box, x: box.x + shift } : box));
  const nodes = { ...layout.nodes };
  for (const [index, box] of moved.entries())
    if (box.x !== boxes[index]!.x) nodes[box.id] = { ...layout.nodes[box.id], x: box.x, y: box.y };
  return {
    layout: { ...layout, nodes },
    position: { x: target.x, y: freeRow(moved, target.x, target.y) },
  };
}

/** Place a component on a link, source → component → target. The target keeps
 * the link's merge position, so execution order elsewhere does not change. */
export function insertOnEdge(
  document: GraphDocument,
  link: Link,
  component: PipelineComponent,
  components: PipelineComponent[],
): { document: GraphDocument; id: string } | undefined {
  const { definition } = document;
  const existing = definition.edges.find(
    (edge) => edge.source === link.source && edge.target === link.target,
  );
  if (!existing || insertBlocker(definition, link, component, components)) return;
  const room = roomOnLink(document, link);
  const added = addComponent({ definition, layout: room.layout }, component, room.position);
  const id = added.definition.nodes[added.definition.nodes.length - 1]!.id;
  return {
    id,
    document: {
      ...added,
      definition: {
        ...added.definition,
        edges: [
          ...added.definition.edges.filter(
            (edge) => edge.source !== link.source || edge.target !== link.target,
          ),
          { source: link.source, target: id, order: 0 },
          { source: id, target: link.target, order: existing.order },
        ],
      },
    },
  };
}

export function moveMergeInput(
  definition: PipelineDefinition,
  target: string,
  index: number,
  direction: -1 | 1,
): PipelineDefinition {
  const incoming = incomingEdges(definition, target);
  const next = index + direction;
  if (!incoming[index] || !incoming[next]) return definition;
  [incoming[index], incoming[next]] = [incoming[next]!, incoming[index]!];
  return {
    ...definition,
    edges: [
      ...definition.edges.filter((edge) => edge.target !== target),
      ...incoming.map((edge, order) => ({ ...edge, order })),
    ],
  };
}
