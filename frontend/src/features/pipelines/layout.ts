import type { PipelineDefinition, PipelineLayout } from "./contracts";

import { notesWithCards } from "./notes";
import { NODE_SIZE } from "./semantics";

export async function arrangeGraph(
  definition: PipelineDefinition,
  layout: PipelineLayout,
): Promise<PipelineLayout> {
  const { default: ELK } = await import("elkjs/lib/elk.bundled.js");
  const elk = new ELK();
  // A draft may keep a connection to a step that is gone; there is nothing to lay it out along.
  const present = new Set(definition.nodes.map((node) => node.id));
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
      ...NODE_SIZE,
    })),
    edges: definition.edges.filter((edge) => present.has(edge.source) && present.has(edge.target)).map((edge, index) => ({
      id: `edge-${index}`,
      sources: [edge.source],
      targets: [edge.target],
    })),
  });
  // A note goes with the card it stood beside.
  return notesWithCards({ definition, layout }, {
    ...layout,
    nodes: Object.fromEntries(
      (arranged.children ?? []).map((node) => [
        node.id,
        { ...layout.nodes[node.id], x: node.x ?? 0, y: node.y ?? 0 },
      ]),
    ),
  });
}
