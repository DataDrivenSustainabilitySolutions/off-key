import { describe, expect, it } from "vitest";
import { normalizeDefinition, normalizeLayout } from "@/features/pipelines/contracts";
import { arrangeGraph } from "@/features/pipelines/layout";

const definition = (edges: Array<{ source: string; target: string }>) => normalizeDefinition({
  nodes: [
    { id: "input", kind: "source", component: "source.aligned" },
    { id: "smooth", kind: "transform", component: "prepare.smooth" },
    { id: "detector", kind: "detector", component: "detector:a" },
  ],
  edges,
});

describe("arranging a design", () => {
  it("lays the steps out from left to right", async () => {
    const layout = normalizeLayout({ nodes: { smooth: { x: 900, y: 900 }, gone: { x: 1, y: 2 } } });
    const arranged = await arrangeGraph(definition([{ source: "input", target: "smooth" }, { source: "smooth", target: "detector" }]), layout);
    expect(Object.keys(arranged.nodes)).toEqual(["input", "smooth", "detector"]);
    expect(arranged.nodes.input!.x).toBeLessThan(arranged.nodes.smooth!.x);
    expect(arranged.nodes.smooth!.x).toBeLessThan(arranged.nodes.detector!.x);
  });

  it("takes a note along with the card it stood beside", async () => {
    const layout = normalizeLayout({
      nodes: { input: { x: 640, y: 320 }, smooth: { x: 0, y: 320 }, detector: { x: 320, y: 0 } },
      // Above the smoothing step, where the cards stand before they are arranged.
      notes: [{ id: "note_1", x: 0, y: 224, text: "Calm it down first." }],
    });
    const arranged = await arrangeGraph(definition([{ source: "input", target: "smooth" }, { source: "smooth", target: "detector" }]), layout);
    const [note] = arranged.notes!;
    const smooth = arranged.nodes.smooth!;
    expect(smooth.x).toBeGreaterThan(0);
    // As far above the card as before, to the nearest line of the grid.
    expect(Math.abs(note!.x - smooth.x)).toBeLessThanOrEqual(8);
    expect(Math.abs(smooth.y - note!.y - 96)).toBeLessThanOrEqual(8);
    expect(note).toMatchObject({ id: "note_1", text: "Calm it down first." });
  });

  it("leaves aside a connection to a step that is gone", async () => {
    const arranged = await arrangeGraph(definition([{ source: "input", target: "smooth" }, { source: "smooth", target: "nowhere" },
      { source: "ghost", target: "detector" }]), normalizeLayout());
    expect(Object.keys(arranged.nodes)).toEqual(["input", "smooth", "detector"]);
    expect(arranged.nodes.input!.x).toBeLessThan(arranged.nodes.smooth!.x);
  });
});
