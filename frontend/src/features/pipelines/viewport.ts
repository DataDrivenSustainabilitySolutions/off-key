import type { ReactFlowInstance } from "@xyflow/react";
import type { CanvasNode } from "./types";

/**
 * Room kept between the canvas edge and a card. A fitted view and a revealed card
 * use the same room, so resizing the canvas never nudges a view that was just fitted.
 */
export const VIEW_MARGIN = 32;

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
  // Graphs read from the left, so centring a selection never pans past the graph's start.
  await flow.setViewport({
    x: Math.min(VIEW_MARGIN - bounds.x, selected ? width / 2 - focus.x - focus.width / 2 : VIEW_MARGIN - focus.x),
    y: height / 2 - focus.y - focus.height / 2,
    zoom: 1,
  });
}

/** Pan, without zooming, until a component is fully inside the visible canvas. */
export async function revealNode(
  flow: ReactFlowInstance<CanvasNode>,
  surface: HTMLElement,
  id: string,
  margin = VIEW_MARGIN,
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
