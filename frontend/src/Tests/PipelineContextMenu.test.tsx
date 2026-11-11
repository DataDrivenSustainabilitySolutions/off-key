import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReactFlowProvider, type NodeProps } from "@xyflow/react";
import { stepMenu } from "@/features/pipelines/contextMenu";
import {
  addAfter, afterBlocker, disconnectNode, duplicateBlocker, duplicateNode, type GraphDocument,
} from "@/features/pipelines/model";
import { PipelineContextMenu } from "@/features/pipelines/PipelineContextMenu";
import { PipelineNodeCard } from "@/features/pipelines/PipelineNodeCard";
import { CardActionsContext } from "@/features/pipelines/cardActions";
import type { CanvasNode } from "@/features/pipelines/types";
import { normalizeDefinition, normalizeLayout, type PipelineComponent } from "@/features/pipelines/contracts";

const component = (id: string, kind: PipelineComponent["kind"], label: string, extra: Partial<PipelineComponent> = {}) => ({
  id, kind, label, description: "", fields: [],
  input_type: kind === "source" ? null : kind === "policy" ? "scores" : kind === "output" ? "decisions" : "features",
  output_type: kind === "detector" ? "scores" : kind === "policy" ? "decisions" : kind === "output" ? null : "features",
  ...extra,
}) as PipelineComponent;

const components = [
  component("source.aligned", "source", "Aligned inputs"),
  component("prepare.smooth", "transform", "Smooth"),
  component("prepare.despike", "transform", "Despike"),
  component("adaptive.standard_scaler", "transform", "Standard scaler"),
  component("detector:aberrant_knn", "detector", "KNN"),
  component("policy.quantile", "policy", "Quantile"),
];

const document = (): GraphDocument => ({
  definition: normalizeDefinition({
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "smooth", kind: "transform", component: "prepare.smooth", params: { window: 7 } },
      { id: "model", kind: "detector", component: "detector:aberrant_knn" },
    ],
    edges: [{ source: "input", target: "smooth" }, { source: "smooth", target: "model" }],
  }),
  layout: normalizeLayout({ nodes: { input: { x: 0, y: 0 }, smooth: { x: 320, y: 0, label: "Calm" }, model: { x: 640, y: 0 } } }),
});

describe("card menu operations", () => {
  it("duplicates a step with its settings and title below the original, unconnected", () => {
    const result = duplicateNode(document(), "smooth", components)!;
    const copy = result.document.definition.nodes.find((node) => node.id === result.id)!;
    expect(copy.params).toEqual({ window: 7 });
    expect(result.document.layout.nodes[result.id]).toMatchObject({ x: 320, label: "Calm copy" });
    expect(result.document.layout.nodes[result.id]!.y).toBeGreaterThan(0);
    expect(result.document.definition.edges.some((edge) => edge.source === result.id || edge.target === result.id)).toBe(false);
  });

  it("does not copy one-per-design steps or detectors", () => {
    expect(duplicateBlocker(document().definition, "input", components)).toBe("A design has one of these.");
    expect(duplicateBlocker(document().definition, "model", components)).toMatch(/detector's settings/);
    expect(duplicateNode(document(), "model", components)).toBeUndefined();
  });

  it("puts a step after a card on its only connection, so the chain stays a chain", () => {
    const despike = components.find((item) => item.id === "prepare.despike")!;
    const result = addAfter(document(), "smooth", despike, components)!;
    const edges = result.document.definition.edges.map((edge) => `${edge.source}>${edge.target}`);
    expect(edges).toEqual(expect.arrayContaining([`smooth>${result.id}`, `${result.id}>model`]));
    expect(edges).not.toContain("smooth>model");
  });

  it("starts a branch when the card has no connection out, and refuses steps that cannot follow", () => {
    const despike = components.find((item) => item.id === "prepare.despike")!;
    const open = { ...document(), definition: disconnectNode(document(), "model").definition };
    const result = addAfter(open, "smooth", despike, components)!;
    expect(result.document.definition.edges).toContainEqual({ source: "smooth", target: result.id, order: 0 });
    const quantile = components.find((item) => item.id === "policy.quantile")!;
    expect(afterBlocker(document(), "smooth", quantile, components)).toBe("Does not take this step's output.");
  });

  it("disconnects every wire of a card and keeps the card", () => {
    const result = disconnectNode(document(), "smooth");
    expect(result.definition.edges).toEqual([]);
    expect(result.definition.nodes).toHaveLength(3);
  });
});

describe("canvas context menu", () => {
  const steps = components.filter((item) => item.kind === "transform");
  const open = (pick = vi.fn(), onClose = vi.fn()) => {
    render(<PipelineContextMenu x={100} y={100} onClose={onClose}
      menu={stepMenu("Add a step", steps, pick, "Nothing fits.")} />);
    return { pick, onClose, search: screen.getByRole("searchbox", { name: "Search steps" }) };
  };

  it("lists step families that open their steps, and adds the one chosen", () => {
    const { pick, onClose, search } = open();
    expect(window.document.activeElement).toBe(search);
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["Prepare2", "Normalize1"]);
    fireEvent.keyDown(search, { key: "ArrowRight" });
    expect(screen.queryByRole("menu", { name: "Prepare" })).not.toBeNull();
    fireEvent.keyDown(search, { key: "ArrowDown" });
    fireEvent.keyDown(search, { key: "Enter" });
    expect(onClose).toHaveBeenCalledWith(false);
    expect(pick).toHaveBeenCalledWith(steps[1]);
  });

  it("narrows to matching steps while typing", () => {
    const { pick, search } = open();
    fireEvent.change(search, { target: { value: "scal" } });
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["Standard scalerNormalize"]);
    fireEvent.keyDown(search, { key: "Enter" });
    expect(pick).toHaveBeenCalledWith(steps[2]);
  });

  it("moves through the entries with the mouse wheel and opens the family it lands on", () => {
    open();
    const families = screen.getByRole("menu", { name: "Add a step" });
    fireEvent.wheel(families, { deltaY: 40 });
    expect(screen.getByRole("menuitem", { name: /Normalize/ }).getAttribute("data-active")).toBe("true");
    expect(screen.queryByRole("menu", { name: "Normalize" })).not.toBeNull();
  });

  it("closes one level with Escape, then the menu, returning focus", () => {
    const { onClose, search } = open();
    fireEvent.keyDown(search, { key: "ArrowRight" });
    fireEvent.keyDown(search, { key: "Escape" });
    expect(screen.queryByRole("menu", { name: "Prepare" })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(search, { key: "Escape" });
    expect(onClose).toHaveBeenCalledWith(true);
  });

  it("keeps typing in the menu after its Back button closes a submenu", () => {
    const { search } = open();
    fireEvent.keyDown(search, { key: "ArrowRight" });
    const back = screen.getByRole("button", { name: "Back from Prepare" });
    back.focus();
    fireEvent.click(back);
    expect(screen.queryByRole("menu", { name: "Prepare" })).toBeNull();
    expect(window.document.activeElement).toBe(search);
  });

  it("keeps a blocked entry readable but does not run it", () => {
    const run = vi.fn();
    render(<PipelineContextMenu x={0} y={0} onClose={vi.fn()} menu={{ label: "Smooth", items: [
      { key: "duplicate", label: "Duplicate", blocked: "A design has one of these.", run },
    ] }} />);
    const item = screen.getByRole("menuitem", { name: /Duplicate/ });
    expect(item.getAttribute("aria-disabled")).toBe("true");
    expect(item.textContent).toContain("A design has one of these.");
    fireEvent.click(item);
    expect(run).not.toHaveBeenCalled();
  });
});

describe("renaming on the card", () => {
  const card = (finishRename = vi.fn()) => {
    const data = {
      label: "Calm", kind: "transform", family: "Prepare", operation: "Smooth", available: true,
      inputPort: true, outputPort: true, issueCount: 0, renaming: true,
    } as CanvasNode["data"];
    const props = { id: "smooth", data, selected: false, isConnectable: true } as unknown as NodeProps<CanvasNode>;
    render(<ReactFlowProvider><CardActionsContext.Provider value={{ finishRename }}>
      <PipelineNodeCard {...props} />
    </CardActionsContext.Provider></ReactFlowProvider>);
    return { finishRename, input: screen.getByRole("textbox", { name: "Step title" }) as HTMLInputElement };
  };

  it("types over the title in place and keeps it with Enter", () => {
    const { finishRename, input } = card();
    expect(window.document.activeElement).toBe(input);
    expect(input.value).toBe("Calm");
    fireEvent.change(input, { target: { value: "Quiet" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(finishRename).toHaveBeenCalledExactlyOnceWith("smooth", "Quiet");
  });

  it("keeps the old title with Escape, and keeps keys away from the canvas", () => {
    const outside = vi.fn();
    window.document.addEventListener("keydown", outside);
    const { finishRename, input } = card();
    fireEvent.keyDown(input, { key: "Backspace" });
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.blur(input);
    window.document.removeEventListener("keydown", outside);
    expect(outside).not.toHaveBeenCalled();
    expect(finishRename).toHaveBeenCalledExactlyOnceWith("smooth", undefined);
  });
});
