import type { ReactFlowInstance } from "@xyflow/react";
import type { CanvasNode } from "./PipelineNodeCard";

/** Fit small graphs; start larger ones at the input without shrinking the type. */
export async function fitReadableView(
  flow: ReactFlowInstance<CanvasNode>,
  surface: HTMLElement,
  selected?: string,
) {
  if (!(await flow.fitView({ minZoom: 1, maxZoom: 1, padding: 0.08 }))) return;
  const nodes = flow.getNodes();
  const bounds = flow.getNodesBounds(nodes);
  const { width, height } = surface.getBoundingClientRect();
  if (!width || !height || (bounds.width + 48 <= width && bounds.height + 48 <= height)) return;
  const anchor = nodes.find((node) => node.id === selected)
    ?? nodes.find((node) => node.data.kind === "source") ?? nodes[0];
  if (!anchor) return;
  const focus = flow.getNodesBounds([anchor]);
  await flow.setViewport({
    x: selected ? width / 2 - focus.x - focus.width / 2 : 24 - focus.x,
    y: height / 2 - focus.y - focus.height / 2,
    zoom: 1,
  });
}
