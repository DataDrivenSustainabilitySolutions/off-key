import { useCallback, useEffect, useState } from "react";
import type { PipelineBlockCreate } from "@/types/pipelines.generated";
import type { BlockStep, PipelineBlock, PipelineComponent, PipelineDefinition, PipelineNode } from "./contracts";
import { pipelinesApi } from "./api";
import { counterpartBefore } from "./learning";
import {
  addBlocker, addComponent, connectNodes, connectionIssue, insertBlocker, insertOnEdge, nodeLabel, PIPELINE_LIMITS,
  setNodeLabel, type GraphDocument, type Link,
} from "./model";

/** The steps a block can hold from a step on: the step and those that follow it one
 * after another, up to a branch, a merge, a detector or the length a block may have. */
export function blockChain(definition: PipelineDefinition, nodeId: string): PipelineNode[] {
  const chain: PipelineNode[] = [];
  let node = definition.nodes.find((item) => item.id === nodeId);
  while (node?.kind === "transform" && chain.length < PIPELINE_LIMITS.blockSteps && !chain.includes(node)) {
    chain.push(node);
    const outgoing = definition.edges.filter((edge) => edge.source === node!.id);
    node = outgoing.length === 1 ? definition.nodes.find((item) => item.id === outgoing[0]!.target) : undefined;
  }
  return chain;
}

/** A chain's steps as a block keeps them: settings and titles, without ids or positions. */
export const blockSteps = (document: GraphDocument, chain: PipelineNode[]): BlockStep[] =>
  chain.map((node) => {
    const label = document.layout.nodes[node.id]?.label;
    return {
      component: node.component,
      contract_version: node.contract_version ?? 1,
      params: structuredClone(node.params),
      ...(label ? { label } : {}),
    };
  });

/** The names of a block's steps, for the line below its name. */
export function blockSummary(steps: BlockStep[], components: PipelineComponent[]) {
  const names = steps.map((step) => step.label
    ?? nodeLabel({ id: "", kind: "transform", component: step.component, params: {} }, components));
  return names.length > 3 ? `${names.slice(0, 3).join(", ")} and ${names.length - 3} more` : names.join(", ");
}

/** What adding a block gives: the design with its steps and the first of them, or why it cannot be added. */
export type BlockOutcome = { document: GraphDocument; id: string } | { blocked: string };
export const blockedBy = (outcome: BlockOutcome) => ("blocked" in outcome ? outcome.blocked : undefined);

type Fitted = { component: PipelineComponent; params: PipelineNode["params"] };
const MISSING = "Holds a step this version does not offer.";
const asNode = (step: BlockStep): PipelineNode =>
  ({ id: "", kind: "transform", component: step.component, contract_version: step.contract_version, params: step.params });

/** A block as a menu offers it: what it holds, and what adding it here gives. */
export type BlockChoice = { block: PipelineBlock; detail: string; outcome: BlockOutcome };
export const blockChoices = (
  blocks: PipelineBlock[], components: PipelineComponent[], add: (block: PipelineBlock) => BlockOutcome,
): BlockChoice[] => blocks.map((block) => ({
  block, detail: block.description || blockSummary(block.steps, components), outcome: add(block),
}));

/** A block's step as the catalogue offers it now. */
function offered(step: BlockStep, components: PipelineComponent[]): Fitted | undefined {
  const component = components.find((item) => item.id === step.component && item.kind === "transform"
    && (item.contract_version ?? 1) === step.contract_version);
  return component && { component, params: step.params };
}

/** A block has room when the design can take all its steps and their connections. */
function roomBlocker(definition: PipelineDefinition, block: PipelineBlock, connections: number) {
  const room = PIPELINE_LIMITS.nodes - definition.nodes.length;
  if (block.steps.length > room) return room > 0
    ? `Has ${block.steps.length} steps, and the design has room for ${room}.`
    : `The design has reached its ${PIPELINE_LIMITS.nodes}-component limit.`;
  if (definition.edges.length + connections > PIPELINE_LIMITS.edges)
    return `The design has reached its ${PIPELINE_LIMITS.edges}-connection limit.`;
}

const lastNode = (document: GraphDocument) => document.definition.nodes[document.definition.nodes.length - 1]!.id;
const titled = (document: GraphDocument, id: string, step: BlockStep) =>
  step.label ? setNodeLabel(document, id, step.label) : document;

/** Add a block's steps as a chain of their own, connected to each other and to nothing else. */
export function placeBlock(
  document: GraphDocument,
  block: PipelineBlock,
  components: PipelineComponent[],
  position?: { x: number; y: number },
  anchor?: string,
): BlockOutcome {
  const full = roomBlocker(document.definition, block, block.steps.length - 1);
  if (full) return { blocked: full };
  let current = document;
  let first: string | undefined;
  let previous: string | undefined;
  for (const step of block.steps) {
    const saved = offered(step, components);
    if (!saved) return { blocked: MISSING };
    const reason = addBlocker(current.definition, saved.component);
    if (reason) return { blocked: reason };
    // Each step sits to the right of the one before it.
    const added = addComponent(current, saved.component, previous ? undefined : position, previous ?? anchor, saved.params, true);
    const id = lastNode(added);
    current = titled(added, id, step);
    if (previous) current = { ...current, definition: connectNodes(current.definition, previous, id, components) };
    first ??= id;
    previous = id;
  }
  return { document: current, id: first! };
}

/** Place a block's steps on a link, one after another. A learned step that does not learn
 * as the detector there does moves to its counterpart, as when a detector's model changes. */
export function insertBlock(
  document: GraphDocument,
  link: Link,
  block: PipelineBlock,
  components: PipelineComponent[],
): BlockOutcome {
  const full = roomBlocker(document.definition, block, block.steps.length);
  if (full) return { blocked: full };
  let current = document;
  let first: string | undefined;
  let source = link.source;
  for (const step of block.steps) {
    const next = { source, target: link.target };
    const saved = offered(step, components);
    if (!saved) return { blocked: MISSING };
    const reason = insertBlocker(current.definition, next, saved.component, components);
    const other = reason ? counterpartBefore(current.definition, link.target, asNode(step), components) : undefined;
    const fitted = reason && other && !insertBlocker(current.definition, next, other.component, components) ? other : saved;
    const inserted = insertOnEdge(current, next, fitted.component, components, fitted.params);
    if (!inserted) return { blocked: reason ?? "Does not fit this connection." };
    current = titled(inserted.document, inserted.id, step);
    first ??= inserted.id;
    source = inserted.id;
  }
  return { document: current, id: first! };
}

/** Add a block after a node: on its one connection out when the block fits there, so a
 * chain stays a chain, otherwise as a new branch beside the node. */
export function addBlockAfter(
  document: GraphDocument,
  nodeId: string,
  block: PipelineBlock,
  components: PipelineComponent[],
): BlockOutcome {
  const outgoing = document.definition.edges.filter((edge) => edge.source === nodeId);
  if (outgoing.length === 1) {
    const inserted = insertBlock(document, outgoing[0]!, block, components);
    if (!blockedBy(inserted)) return inserted;
  }
  const placed = placeBlock(document, block, components, undefined, nodeId);
  if ("blocked" in placed) return placed;
  if (connectionIssue(placed.document.definition, nodeId, placed.id, components))
    return { blocked: "Does not take this step's output." };
  return { id: placed.id, document: { ...placed.document, definition: connectNodes(placed.document.definition, nodeId, placed.id, components) } };
}

/** The library's blocks for an editor, which can also save one more. The menus list
 * blocks as they are known; a failed load leaves them empty and the steps as they were. */
export function useBlocks(enabled: boolean) {
  const [blocks, setBlocks] = useState<PipelineBlock[]>([]);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void pipelinesApi.blocks(controller.signal).then(
      (loaded) => { if (!controller.signal.aborted) setBlocks(loaded); },
      () => {},
    );
    return () => controller.abort();
  }, [enabled]);
  const save = useCallback(async (request: PipelineBlockCreate) => {
    const saved = await pipelinesApi.createBlock(request);
    setBlocks((previous) => [...previous, saved].sort((left, right) =>
      left.name.localeCompare(right.name, undefined, { sensitivity: "base" })));
  }, []);
  return { blocks: enabled ? blocks : [], save };
}
