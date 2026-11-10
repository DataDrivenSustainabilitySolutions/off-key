import type { ReactFlowInstance } from "@xyflow/react";
import type { CanvasNode } from "./types";

/**
 * Room kept between the canvas edge and a card. A fitted view and a revealed card
 * use the same room, so resizing the canvas never nudges a view that was just fitted.
 */
export const VIEW_MARGIN = 32;

/** Canvas edges covered by floating controls, in screen pixels. */
export type CoveredEdges = { top?: number; right?: number; bottom?: number };

/** Uncovered room kept on a canvas whose floating controls cover nearly all of it. */
const MIN_VISIBLE = 96;
const clampCover = (cover: number | undefined, room: number) =>
  Math.max(0, Math.min(cover ?? 0, room - MIN_VISIBLE));

/** The part of the surface no floating control covers, relative to its top left corner. */
function visibleArea(surface: HTMLElement, covered?: CoveredEdges) {
  const { width, height } = surface.getBoundingClientRect();
  // Covers count as measured, so a tall bottom sheet keeps revealed cards above it.
  const top = clampCover(covered?.top, height);
  const right = clampCover(covered?.right, width);
  const bottom = clampCover(covered?.bottom, height - top);
  return { top, width: width - right, height: height - top - bottom, empty: !width || !height };
}

/** Fit small graphs; start larger ones at the input without shrinking the type. */
export async function fitReadableView(
  flow: ReactFlowInstance<CanvasNode>,
  surface: HTMLElement,
  selected?: string,
  covered?: CoveredEdges,
) {
  if (!(await flow.fitView({ minZoom: 1, maxZoom: 1, padding: 0.08 }))) return;
  const nodes = flow.getNodes();
  const bounds = flow.getNodesBounds(nodes);
  const { top, width, height, empty } = visibleArea(surface, covered);
  if (empty) return;
  if (bounds.width + 48 <= width && bounds.height + 48 <= height) {
    // A graph that fits is centred in the part of the canvas left uncovered.
    if (top || covered?.right || covered?.bottom) await flow.setViewport({
      x: width / 2 - bounds.x - bounds.width / 2, y: top + height / 2 - bounds.y - bounds.height / 2, zoom: 1 });
    return;
  }
  const anchor = nodes.find((node) => node.id === selected)
    ?? nodes.find((node) => node.data.kind === "source") ?? nodes[0];
  if (!anchor) return;
  const focus = flow.getNodesBounds([anchor]);
  // Graphs read from the left, so centring a selection never pans past the graph's start.
  await flow.setViewport({
    x: Math.min(VIEW_MARGIN - bounds.x, selected ? width / 2 - focus.x - focus.width / 2 : VIEW_MARGIN - focus.x),
    y: top + height / 2 - focus.y - focus.height / 2,
    zoom: 1,
  });
}

/** Pan, without zooming, until a component is fully inside the visible canvas. */
export async function revealNode(
  flow: ReactFlowInstance<CanvasNode>,
  surface: HTMLElement,
  id: string,
  margin = VIEW_MARGIN,
  covered?: CoveredEdges,
) {
  const node = flow.getNode(id);
  if (!node) return;
  const bounds = flow.getNodesBounds([node]);
  const { x, y, zoom } = flow.getViewport();
  const area = visibleArea(surface, covered);
  if (area.empty) return;
  const { width, height } = area;
  const left = bounds.x * zoom + x;
  const top = bounds.y * zoom + y - area.top;
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
