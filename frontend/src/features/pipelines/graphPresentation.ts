import { MarkerType, type Edge } from "@xyflow/react";
import type { PipelineComponent, PipelineValidation } from "./contracts";
import type { CanvasNode } from "./types";
import { incomingEdges, nodeLabel, nodeOptionLabel, type GraphDocument } from "./model";
import {
  componentFor,
  dataKinds,
  edgeId,
  inputKind,
  NODE_SIZE,
  nodePosition,
  outputKind,
} from "./semantics";

/** Project the canonical definition into the renderer. Never normalize or mutate execution here. */
export function presentGraph(
  document: GraphDocument,
  components: PipelineComponent[],
  states?: Record<string, string>,
  issues: PipelineValidation["issues"] = [],
) {
  const nodes: CanvasNode[] = document.definition.nodes.map((node, index) => {
    const component = componentFor(node, components);
    const input = inputKind(component);
    const output = outputKind(node, component);
    return {
      id: node.id,
      type: "component",
      position: nodePosition(document.layout, node.id, index),
      style: NODE_SIZE,
      ariaLabel: nodeOptionLabel(node, document, components),
      data: {
        label: nodeLabel(node, components, document.layout),
        kind: node.kind,
        operation: component?.label ?? node.component,
        available: !!component,
        inputPort: component ? !!input : node.kind !== "source",
        outputPort: component ? !!output : node.kind !== "output",
        inputType: input,
        outputType: output,
        state: states?.[node.id],
        issueCount: issues.filter((issue) => issue.node_id === node.id).length,
      },
    };
  });
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const ranks = new Map<string, number>();
  for (const node of nodes)
    incomingEdges(document.definition, node.id)
      .forEach((edge, index) => ranks.set(edgeId(edge), index + 1));
  const edges: Edge[] = document.definition.edges.map((edge) => {
    const source = byId.get(edge.source);
    const target = byId.get(edge.target);
    const kind = source?.data.outputType;
    const type = kind ? dataKinds[kind].label : "Unavailable type";
    const suffix =
      target?.data.kind === "merge"
        ? ` · input ${ranks.get(edgeId(edge))}`
        : "";
    const color = kind ? `var(--pl-${kind})` : "hsl(var(--muted-foreground))";
    return {
      id: edgeId(edge),
      source: edge.source,
      target: edge.target,
      sourceHandle: "output",
      targetHandle: "input",
      className: `pl-data--${kind ?? "unknown"}`,
      style: {
        strokeWidth: 2,
        stroke: color,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color },
      ariaLabel: `${source?.ariaLabel ?? edge.source} to ${target?.ariaLabel ?? edge.target}: ${type}${suffix}`,
    };
  });
  return { nodes, edges };
}
