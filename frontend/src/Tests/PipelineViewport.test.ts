import { describe, expect, it, vi } from "vitest";
import type { ReactFlowInstance } from "@xyflow/react";

import type { CanvasNode } from "@/features/pipelines/PipelineNodeCard";
import { fitReadableView, revealNode } from "@/features/pipelines/viewport";

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
    ["starts at the input", wideGraph, undefined, { x: 24, y: 70, zoom: 1 }],
    ["centres the selection", wideGraph, "model", { x: -450, y: 110, zoom: 1 }],
    [
      "starts at the first component without an input",
      wideGraph.slice(0, 1).concat({ ...wideGraph[0]!, id: "late", x: 0 }),
      undefined,
      { x: -576, y: 110, zoom: 1 },
    ],
  ])("%s of a graph too large to read when fitted", async (_, placed, selected, view) => {
    const { flow, instance } = canvas(placed);

    await fitReadableView(instance, surface(500, 300), selected);

    expect(flow.setViewport).toHaveBeenCalledExactlyOnceWith(view);
  });
});

describe("revealNode", () => {
  const viewport = { x: 10, y: 20, zoom: 2 };

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
