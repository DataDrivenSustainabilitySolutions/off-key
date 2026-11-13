// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import type { ReactFlowInstance } from "@xyflow/react";

import type { CanvasNode } from "@/features/pipelines/types";
import { fitReadableView, READABLE_ZOOM, revealNode, smallestZoom, VIEW_MARGIN } from "@/features/pipelines/viewport";

type Box = { x: number; y: number; width: number; height: number };
type Placed = Box & { id: string; kind?: string };

/** A React Flow stand-in whose bounds are the union of plain node boxes. */
function canvas(
  placed: Placed[],
  { fits = true, viewport = { x: 0, y: 0, zoom: 1 } } = {},
) {
  const nodes = placed.map(({ id, kind = "transform", ...box }) => ({
    id,
    box,
    data: { kind },
  }));
  const bounds = (list: typeof nodes): Box => {
    const left = Math.min(...list.map(({ box }) => box.x));
    const top = Math.min(...list.map(({ box }) => box.y));
    return {
      x: left,
      y: top,
      width: Math.max(...list.map(({ box }) => box.x + box.width)) - left,
      height: Math.max(...list.map(({ box }) => box.y + box.height)) - top,
    };
  };
  const flow = {
    fitView: vi.fn().mockResolvedValue(fits),
    getNodes: () => nodes,
    getNode: (id: string) => nodes.find((node) => node.id === id),
    getNodesBounds: bounds,
    getViewport: () => viewport,
    setViewport: vi.fn().mockResolvedValue(true),
  };
  return {
    flow,
    instance: flow as unknown as ReactFlowInstance<CanvasNode>,
  };
}

const surface = (width: number, height: number) =>
  ({ getBoundingClientRect: () => ({ width, height }) }) as HTMLElement;

/** A model wider than the 500 × 300 surface, with its input listed second. */
const wideGraph: Placed[] = [
  { id: "model", x: 600, y: 0, width: 200, height: 80 },
  { id: "input", kind: "source", x: 0, y: 40, width: 200, height: 80 },
];

describe("fitReadableView", () => {
  it.each([
    ["fitting fails", wideGraph, false, surface(500, 300)],
    ["the surface has no size yet", wideGraph, true, surface(0, 300)],
    [
      "the graph fits with room to spare",
      [{ id: "model", x: 0, y: 0, width: 200, height: 80 }],
      true,
      surface(500, 300),
    ],
  ])("keeps the fitted view when %s", async (_, placed, fits, element) => {
    const { flow, instance } = canvas(placed, { fits });

    await fitReadableView(instance, element);

    expect(flow.fitView).toHaveBeenCalledWith({
      minZoom: 1,
      maxZoom: 1,
      padding: 0.08,
    });
    expect(flow.setViewport).not.toHaveBeenCalled();
  });

  it.each([
    ["starts at the input", wideGraph, undefined, { x: 32, y: 70, zoom: 1 }],
    ["centres the selection", wideGraph, "model", { x: -450, y: 110, zoom: 1 }],
    ["keeps the start in view when centring the input", wideGraph, "input", { x: 32, y: 70, zoom: 1 }],
    [
      "starts at the first component without an input",
      wideGraph.slice(0, 1).concat({ ...wideGraph[0]!, id: "late", x: 0 }),
      undefined,
      { x: -568, y: 110, zoom: 1 },
    ],
  ])("%s of a graph too large to read when fitted", async (_, placed, selected, view) => {
    const { flow, instance } = canvas(placed);

    await fitReadableView(instance, surface(500, 300), selected);

    expect(flow.setViewport).toHaveBeenCalledExactlyOnceWith(view);
  });
});

describe("fitReadableView of a graph that nearly fits", () => {
  /** 560 wide on a 500 wide surface: it fits at 81 %, which stays readable. */
  const nearly: Placed[] = [
    { id: "input", kind: "source", x: 0, y: 0, width: 200, height: 80 },
    { id: "model", x: 360, y: 0, width: 200, height: 80 },
  ];

  it("shows the whole graph a little smaller", async () => {
    const { flow, instance } = canvas(nearly);

    await fitReadableView(instance, surface(500, 300));

    const [view] = flow.setViewport.mock.calls[0]!;
    expect(view.zoom).toBeCloseTo(452 / 560);
    expect(view.zoom).toBeGreaterThanOrEqual(READABLE_ZOOM);
    // Centred: 24 px stay free on either side.
    expect(view.x).toBeCloseTo(24);
    expect(view.y).toBeCloseTo(150 - 40 * (452 / 560));
  });

  it("keeps a graph that would shrink further at full size, from its input", async () => {
    const { flow, instance } = canvas([nearly[0]!, { ...nearly[1]!, x: 400 }]);

    await fitReadableView(instance, surface(500, 300));

    expect(flow.setViewport).toHaveBeenCalledExactlyOnceWith({ x: 32, y: 110, zoom: 1 });
  });
});

describe("revealNode", () => {
  const viewport = { x: 10, y: 20, zoom: 2 };

  it("leaves a view fitted at the start where it is", async () => {
    const start = { x: VIEW_MARGIN, y: 70, zoom: 1 };
    const { flow, instance } = canvas(wideGraph, { viewport: start });

    await revealNode(instance, surface(500, 300), "input");

    expect(flow.setViewport).not.toHaveBeenCalled();
  });

  it.each([
    ["is already visible", { x: 50, y: 40, width: 100, height: 50 }, null],
    [
      "pans right and down into the margin",
      { x: -20, y: -30, width: 100, height: 50 },
      { x: 72, y: 92 },
    ],
    [
      "pans left and up into the margin",
      { x: 200, y: 100, width: 100, height: 50 },
      { x: -132, y: -32 },
    ],
    [
      "centres a component wider than the surface",
      { x: 0, y: 10, width: 300, height: 50 },
      { x: -50, y: 20 },
    ],
  ])("a component that %s", async (_, box, pan) => {
    const { flow, instance } = canvas([{ id: "model", ...box }], { viewport });

    await revealNode(instance, surface(500, 300), "model");

    if (pan) {
      expect(flow.setViewport).toHaveBeenCalledExactlyOnceWith(
        { ...pan, zoom: 2 },
        { duration: 200 },
      );
    } else {
      expect(flow.setViewport).not.toHaveBeenCalled();
    }
  });

  it("keeps a revealed component above a bottom sheet covering more than half the canvas", async () => {
    const start = { x: 0, y: 0, zoom: 1 };
    const { flow, instance } = canvas([{ id: "model", x: 50, y: 400, width: 100, height: 80 }], { viewport: start });

    await revealNode(instance, surface(400, 600), "model", VIEW_MARGIN, { bottom: 348 });

    // 252 px stay uncovered, so the card ends a margin above the sheet.
    expect(flow.setViewport).toHaveBeenCalledExactlyOnceWith({ x: 0, y: 252 - VIEW_MARGIN - 480, zoom: 1 }, { duration: 200 });
  });

  it.each([
    ["the component is gone", "removed", surface(500, 300)],
    ["the surface has no size yet", "model", surface(500, 0)],
  ])("does nothing when %s", async (_, id, element) => {
    const placed = [{ id: "model", x: -500, y: 0, width: 100, height: 50 }];
    const { flow, instance } = canvas(placed, { viewport });

    await revealNode(instance, element, id);

    expect(flow.setViewport).not.toHaveBeenCalled();
  });
});

describe("smallestZoom", () => {
  const card = (x: number, y = 0) => ({ x, y, width: 224, height: 144 });
  const room = { width: 1296, height: 696 };

  it("stops at a quarter of full size where the graph is in view long before", () => {
    expect(smallestZoom([card(0), card(288), card(576)], room)).toBe(0.25);
    // Nothing to measure against yet.
    expect(smallestZoom([], room)).toBe(0.25);
    expect(smallestZoom([card(0)])).toBe(0.25);
  });

  it("goes further out for a graph that a quarter of full size does not show whole", () => {
    // Sixty-five cards in a row are 18,656 px wide; 1,200 px of room show them at 6.4%.
    const row = Array.from({ length: 65 }, (_, index) => card(index * 288));
    const zoom = smallestZoom(row, room);
    expect(zoom).toBe(0.05);
    expect(zoom * 18_656).toBeLessThan(1_200);
    // Settings over the right edge leave less room, and a tall graph is bounded by its height.
    expect(smallestZoom(row, room, { right: 400 })).toBe(0.03);
    expect(smallestZoom(Array.from({ length: 30 }, (_, index) => card(0, index * 176)), room)).toBe(0.1);
  });

  it("never reaches zero, however little room is left", () => {
    expect(smallestZoom([card(0), card(288)], { width: 96, height: 96 })).toBe(0.01);
  });
});
