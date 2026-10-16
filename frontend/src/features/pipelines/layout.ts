import type { PipelineDefinition, PipelineLayout } from "./contracts";

export async function arrangeGraph(
  definition: PipelineDefinition,
  layout: PipelineLayout,
): Promise<PipelineLayout> {
  const { default: ELK } = await import("elkjs/lib/elk.bundled.js");
  const elk = new ELK();
  const arranged = await elk.layout({
    id: "pipeline",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.spacing.nodeNode": "45",
      "elk.layered.spacing.nodeNodeBetweenLayers": "70",
    },
    children: definition.nodes.map((node) => ({
      id: node.id,
      width: 190,
      height: 96,
    })),
    edges: definition.edges.map((edge, index) => ({
      id: `edge-${index}`,
      sources: [edge.source],
      targets: [edge.target],
    })),
  });
  return {
    ...layout,
    nodes: Object.fromEntries(
      (arranged.children ?? []).map((node) => [
        node.id,
        { ...layout.nodes[node.id], x: node.x ?? 0, y: node.y ?? 0 },
      ]),
    ),
  };
}
