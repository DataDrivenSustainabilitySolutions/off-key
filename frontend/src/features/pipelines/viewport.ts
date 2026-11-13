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

/** Room a graph fitted whole keeps to the edges of the canvas, in pixels. */
export const FIT_ROOM = 48;

/** Zooming out stops here, where cards can still be told apart. */
const MIN_ZOOM = 0.25;

/**
 * How far the canvas zooms out: to a quarter of full size, or further where a large graph
 * needs it to be seen whole. It is a little under the scale that fits and moves in steps
 * of a hundredth, so dragging a card does not change it at every move.
 */
export function smallestZoom(
  boxes: Array<{ x: number; y: number; width: number; height: number }>,
  room?: { width: number; height: number },
  covered?: CoveredEdges,
) {
  if (!room || !boxes.length) return MIN_ZOOM;
  const across = Math.max(...boxes.map((box) => box.x + box.width)) - Math.min(...boxes.map((box) => box.x));
  const down = Math.max(...boxes.map((box) => box.y + box.height)) - Math.min(...boxes.map((box) => box.y));
  const width = room.width - (covered?.right ?? 0) - 2 * FIT_ROOM;
  const height = room.height - (covered?.top ?? 0) - (covered?.bottom ?? 0) - 2 * FIT_ROOM;
  const whole = Math.floor(90 * Math.min(width / across, height / down)) / 100;
  return Math.max(0.01, Math.min(MIN_ZOOM, whole));
}

/** The smallest a fitted graph is shown: seeing a whole flow is worth a little type size, not more. */
export const READABLE_ZOOM = 0.8;

/** Show a whole graph while its type stays readable; start a larger one at the input at full size. */
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
  const zoom = Math.min(1, (width - 48) / bounds.width, (height - 48) / bounds.height);
  if (zoom >= READABLE_ZOOM) {
    // A graph that fits is centred in the part of the canvas left uncovered.
    if (zoom === 1 && !top && !covered?.right && !covered?.bottom) return;
    await flow.setViewport({
      x: width / 2 - (bounds.x + bounds.width / 2) * zoom,
      y: top + height / 2 - (bounds.y + bounds.height / 2) * zoom,
      zoom,
    });
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

/** Pan, without zooming, until a component, or several taken together, is fully inside the visible canvas. */
export async function revealNode(
  flow: ReactFlowInstance<CanvasNode>,
  surface: HTMLElement,
  id: string | string[],
  margin = VIEW_MARGIN,
  covered?: CoveredEdges,
) {
  const nodes = [id].flat().flatMap((item) => flow.getNode(item) ?? []);
  if (!nodes.length) return;
  const bounds = flow.getNodesBounds(nodes);
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
