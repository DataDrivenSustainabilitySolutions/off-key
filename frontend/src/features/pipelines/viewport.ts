import type { ReactFlowInstance } from "@xyflow/react";
import type { CanvasNode } from "./types";

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

/** Pan, without zooming, until a component is fully inside the visible canvas. */
export async function revealNode(
  flow: ReactFlowInstance<CanvasNode>,
  surface: HTMLElement,
  id: string,
  margin = 32,
) {
  const node = flow.getNode(id);
  if (!node) return;
  const bounds = flow.getNodesBounds([node]);
  const { x, y, zoom } = flow.getViewport();
  const { width, height } = surface.getBoundingClientRect();
  if (!width || !height) return;
  const left = bounds.x * zoom + x;
  const top = bounds.y * zoom + y;
  const right = left + bounds.width * zoom;
  const bottom = top + bounds.height * zoom;
  const shift = (start: number, end: number, size: number) =>
    end - start + margin * 2 > size
      ? size / 2 - (start + end) / 2
      : start < margin ? margin - start : end > size - margin ? size - margin - end : 0;
  const dx = shift(left, right, width);
  const dy = shift(top, bottom, height);
  if (dx || dy) await flow.setViewport({ x: x + dx, y: y + dy, zoom }, { duration: 200 });
}
