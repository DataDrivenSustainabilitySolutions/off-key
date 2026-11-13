import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { pipelinesApi } from "@/features/pipelines/api";
import {
  addBlockAfter, blockChain, blockChoices, blockedBy, blockSteps, blockSummary, insertBlock, placeBlock, useBlocks,
  type BlockOutcome,
} from "@/features/pipelines/blocks";
import { stepMenu, type MenuItem } from "@/features/pipelines/contextMenu";
import {
  normalizeCatalog, normalizeDefinition, normalizeLayout, type BlockStep, type PipelineBlock,
} from "@/features/pipelines/contracts";
import { PIPELINE_LIMITS, type GraphDocument } from "@/features/pipelines/model";
import { PipelineBlockLibrary } from "@/features/pipelines/PipelineBlockLibrary";
import { PipelineContextMenu } from "@/features/pipelines/PipelineContextMenu";
import { PipelineSaveBlock } from "@/features/pipelines/PipelineSaveBlock";
import { PipelineToolbox } from "@/features/pipelines/PipelineToolbox";
import type * as Wire from "@/types/pipelines.generated";

/** A step as the catalog lists it; `facts` are the group it is filed in and the step that learns the other way. */
const component = (id: string, kind: Wire.PipelineComponent["kind"], label: string,
  learning: Wire.PipelineComponent["learning"] = "none", fields: Wire.ComponentField[] = [],
  facts: Partial<Pick<Wire.PipelineComponent, "group" | "counterpart">> = {}): Wire.PipelineComponent => ({
  id, kind, label, description: "", learning, fields,
  group: kind === "source" ? "input" : kind === "transform" ? "prepare" : kind === "merge" ? "route" : kind,
  ...facts,
  input_type: kind === "source" ? null : kind === "policy" ? "scores" : "features",
  output_type: kind === "detector" ? "scores" : kind === "policy" ? "decisions" : "features",
});
const flag = (name: string): Wire.ComponentField => ({ name, label: name, type: "boolean", default: true, has_default: true });
const components = normalizeCatalog({
  catalog_id: "blocks", authoring_enabled: true, templates: [],
  components: [
    component("source.aligned", "source", "Aligned inputs"),
    component("prepare.formula", "transform", "Formula", "none", [], { group: "combine" }),
    component("prepare.smooth", "transform", "Smooth"),
    component("static.standard_scaler", "transform", "Standard scaling", "batch", [flag("with_mean"), flag("with_std")],
      { group: "normalize", counterpart: "adaptive.standard_scaler" }),
    component("adaptive.standard_scaler", "transform", "Standard scaling", "online", [flag("with_std")],
      { group: "normalize", counterpart: "static.standard_scaler" }),
    component("adaptive.only", "transform", "Online only", "online", [], { group: "normalize" }),
    component("detector:pyod_iforest", "detector", "Isolation Forest", "batch"),
    component("detector:aberrant_x_stream", "detector", "xStream", "online"),
    component("policy.quantile", "policy", "Calibrated score threshold"),
  ],
}).components;

/** input → Power → scale → model, learning continuously. */
const design = (detector = "detector:aberrant_x_stream"): GraphDocument => ({
  definition: normalizeDefinition({
    schema_version: 2,
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "power", kind: "transform", component: "prepare.formula", label: "Power", params: { expression: "voltage * current", name: "power" } },
      { id: "scale", kind: "transform", component: detector.includes("pyod") ? "static.standard_scaler" : "adaptive.standard_scaler",
        params: { with_std: false } },
      { id: "model", kind: "detector", component: detector },
    ],
    edges: [{ source: "input", target: "power" }, { source: "power", target: "scale" }, { source: "scale", target: "model" }],
  }),
  layout: normalizeLayout({ nodes: {
    input: { x: 0, y: 0 }, power: { x: 288, y: 0 }, scale: { x: 576, y: 0 }, model: { x: 864, y: 0 },
  } }),
});
/** A design of `count` Smooth steps in a row and nothing else. */
const row = (count: number): GraphDocument => ({
  definition: normalizeDefinition({
    schema_version: 2,
    nodes: Array.from({ length: count }, (_, index) => ({ id: `s${index}`, kind: "transform" as const, component: "prepare.smooth" })),
    edges: Array.from({ length: count - 1 }, (_, index) => ({ source: `s${index}`, target: `s${index + 1}` })),
  }),
  layout: normalizeLayout({ nodes: {} }),
});

const step = (id: string, extra: Partial<BlockStep> = {}): BlockStep => ({ component: id, contract_version: 1, params: {}, ...extra });
const block = (name: string, steps: BlockStep[], description = ""): PipelineBlock =>
  ({ id: name.toLocaleLowerCase().replace(/ /g, "-"), name, description, steps, created_at: "2026-11-12T09:00:00Z" });
const POWER = step("prepare.formula", { params: { expression: "voltage * current", name: "power" }, label: "Power" });
const scaled = block("Power, scaled", [POWER, step("static.standard_scaler", { params: { with_mean: false, with_std: false } })]);
const calm = block("Calm", [step("prepare.smooth")], "Take out short spikes");
const retired = block("Old step", [step("prepare.retired")]);
const placed = (outcome: BlockOutcome) => {
  if ("blocked" in outcome) throw new Error(outcome.blocked);
  return outcome;
};
const wires = (document: GraphDocument) => document.definition.edges.map((edge) => `${edge.source}>${edge.target}`);
const node = (document: GraphDocument, id: string) => document.definition.nodes.find((item) => item.id === id)!;

describe("the steps a block can hold", () => {
  it("runs from a step along its chain and stops before the detector", () => {
    const { definition } = design();
    expect(blockChain(definition, "power").map((item) => item.id)).toEqual(["power", "scale"]);
    expect(blockChain(definition, "scale").map((item) => item.id)).toEqual(["scale"]);
    expect(blockChain(definition, "model")).toEqual([]);
    expect(blockChain(definition, "input")).toEqual([]);
    expect(blockChain(definition, "missing")).toEqual([]);
  });

  it("ends where the steps branch and at the length a block may have", () => {
    const branched = design().definition;
    branched.edges.push({ source: "power", target: "model", order: 1 });
    expect(blockChain(branched, "power").map((item) => item.id)).toEqual(["power"]);
    expect(blockChain(row(PIPELINE_LIMITS.blockSteps + 4).definition, "s0")).toHaveLength(PIPELINE_LIMITS.blockSteps);
    // Steps connected in a ring are each held once.
    const ring = row(3).definition;
    ring.edges.push({ source: "s2", target: "s0", order: 0 });
    expect(blockChain(ring, "s1").map((item) => item.id)).toEqual(["s1", "s2", "s0"]);
  });

  it("keeps settings and titles, and neither ids nor positions", () => {
    const document = design();
    const steps = blockSteps(blockChain(document.definition, "power"));
    expect(steps).toEqual([POWER, step("adaptive.standard_scaler", { params: { with_std: false } })]);
    steps[0]!.params.name = "changed";
    expect(node(document, "power").params.name).toBe("power");
    const titled = design();
    titled.definition.nodes.find((item) => item.id === "scale")!.label = "Scale";
    expect(blockSteps(blockChain(titled.definition, "power")).map((item) => item.label)).toEqual(["Power", "Scale"]);
  });

  it("names up to three of its steps by title", () => {
    expect(blockSummary(scaled.steps, components)).toBe("Power, Standard scaling");
    expect(blockSummary([POWER, ...Array.from({ length: 4 }, () => step("prepare.smooth"))], components))
      .toBe("Power, Smooth, Smooth and 2 more");
  });
});

describe("adding a block beside the design", () => {
  it("adds its steps as a chain of their own with their settings and titles", () => {
    const before = design();
    const result = placed(placeBlock(before, scaled, components, { x: 0, y: 400 }));
    expect(result.id).toBe("prepare_formula_1");
    // The name of the feature stays as saved, although the design already gives one of that name.
    expect(node(result.document, "prepare_formula_1").params).toEqual(POWER.params);
    expect(node(result.document, "static_standard_scaler_1").params).toEqual({ with_mean: false, with_std: false });
    // The title is part of the design; the layout holds where the step stands.
    expect(node(result.document, "prepare_formula_1").label).toBe("Power");
    expect(result.document.layout.nodes.prepare_formula_1).toEqual({ x: 0, y: 400 });
    expect(result.document.layout.nodes.static_standard_scaler_1!.x).toBeGreaterThan(0);
    expect(wires(result.document)).toEqual([...wires(before), "prepare_formula_1>static_standard_scaler_1"]);
    // The block is not tied to the design: changing the design leaves it as it was.
    node(result.document, "prepare_formula_1").params.name = "changed";
    expect(scaled.steps[0]!.params.name).toBe("power");
  });

  it("says why a block cannot be added", () => {
    expect(blockedBy(placeBlock(design(), retired, components))).toBe("Holds a step this version does not offer.");
    const newer = block("Newer", [step("prepare.smooth", { contract_version: 2 })]);
    expect(blockedBy(placeBlock(design(), newer, components))).toBe("Holds a step this version does not offer.");
    expect(blockedBy(placeBlock(row(PIPELINE_LIMITS.nodes - 1), scaled, components)))
      .toBe("Has 2 steps, and the design has room for 1.");
    expect(blockedBy(placeBlock(row(PIPELINE_LIMITS.nodes), calm, components)))
      .toBe(`The design has reached its ${PIPELINE_LIMITS.nodes}-component limit.`);
    expect(blockedBy(placeBlock(design(), calm, components))).toBeUndefined();
  });
});

describe("inserting a block on a connection", () => {
  it("places the steps one after another between the two ends", () => {
    const result = placed(insertBlock(design(), { source: "input", target: "power" },
      block("Two", [step("prepare.smooth", { label: "Calm" }), step("prepare.smooth")]), components));
    expect(result.id).toBe("prepare_smooth_1");
    expect(wires(result.document)).toEqual(expect.arrayContaining([
      "input>prepare_smooth_1", "prepare_smooth_1>prepare_smooth_2", "prepare_smooth_2>power",
    ]));
    expect(wires(result.document)).not.toContain("input>power");
    expect(node(result.document, "prepare_smooth_1").label).toBe("Calm");
  });

  it("moves a learned step to the counterpart that learns as the detector there does", () => {
    const result = placed(insertBlock(design(), { source: "scale", target: "model" }, scaled, components));
    // The settings both versions share are kept; the rest take their defaults.
    expect(node(result.document, "adaptive_standard_scaler_1")).toMatchObject({
      component: "adaptive.standard_scaler", params: { with_std: false },
    });
    expect(wires(result.document)).toEqual(expect.arrayContaining([
      "scale>prepare_formula_1", "prepare_formula_1>adaptive_standard_scaler_1", "adaptive_standard_scaler_1>model",
    ]));
    // Before a detector fitted once the step stays as it was saved.
    const fitted = placed(insertBlock(design("detector:pyod_iforest"), { source: "scale", target: "model" }, scaled, components));
    expect(node(fitted.document, "static_standard_scaler_1").params).toEqual({ with_mean: false, with_std: false });
    // A step without a title is told apart from the one of its kind already there.
    expect(node(fitted.document, "static_standard_scaler_1").label).toBe("Standard scaling 2");
  });

  it("refuses a block with a learned step that has no such counterpart, and leaves the design alone", () => {
    const before = design("detector:pyod_iforest");
    const outcome = insertBlock(before, { source: "scale", target: "model" },
      block("Online", [step("prepare.smooth"), step("adaptive.only")]), components);
    expect(blockedBy(outcome)).toBe("Learns continuously, and the detector here is fitted once.");
    expect(before).toEqual(design("detector:pyod_iforest"));
    expect(blockedBy(insertBlock(design(), { source: "scale", target: "model" }, retired, components)))
      .toBe("Holds a step this version does not offer.");
  });
});

describe("adding a block after a step", () => {
  it("goes on the step's one connection, so a chain stays a chain", () => {
    const result = placed(addBlockAfter(design(), "power", calm, components));
    expect(wires(result.document)).toEqual(expect.arrayContaining(["power>prepare_smooth_1", "prepare_smooth_1>scale"]));
    expect(wires(result.document)).not.toContain("power>scale");
  });

  it("starts a branch where the step has no single connection out", () => {
    const open = design();
    open.definition.edges = open.definition.edges.filter((edge) => edge.source !== "scale");
    const result = placed(addBlockAfter(open, "scale", scaled, components));
    expect(wires(result.document)).toEqual(expect.arrayContaining([
      "scale>prepare_formula_1", "prepare_formula_1>static_standard_scaler_1",
    ]));
    expect(result.id).toBe("prepare_formula_1");
  });

  it("refuses after a step whose output a block's first step does not take", () => {
    expect(blockedBy(addBlockAfter(design(), "model", calm, components))).toBe("Does not take this step's output.");
  });
});

describe("blocks in the step menus", () => {
  const steps = components.filter((item) => item.kind === "transform" && item.learning === "none");
  const entries = (run = vi.fn()): MenuItem[] => blockChoices([scaled, calm, retired], components,
    (item) => placeBlock(design(), item, components)).map(({ block: item, detail, outcome }) => ({
    key: `block:${item.id}`, label: item.name, detail, blocked: blockedBy(outcome), run: () => run(item.name),
  }));

  it("says what each block holds, by its description or its steps", () => {
    expect(entries().map((item) => [item.label, item.detail, item.blocked])).toEqual([
      ["Power, scaled", "Power, Standard scaling", undefined],
      ["Calm", "Take out short spikes", undefined],
      ["Old step", "prepare.retired", "Holds a step this version does not offer."],
    ]);
  });

  it("lists blocks as one more group that opens them, and keeps one that cannot be added readable", () => {
    const run = vi.fn();
    render(<PipelineContextMenu x={100} y={100} onClose={vi.fn()}
      menu={stepMenu("Add a step", steps, vi.fn(), "Nothing fits.", entries(run))} />);
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["Prepare1", "Combine1", "Blocks3"]);
    fireEvent.click(screen.getByRole("menuitem", { name: /Blocks/ }));
    const group = within(screen.getByRole("menu", { name: "Blocks" }));
    const old = group.getByRole("menuitem", { name: /Old step/ });
    expect(old.getAttribute("aria-disabled")).toBe("true");
    expect(old.textContent).toContain("Holds a step this version does not offer.");
    fireEvent.click(old);
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(group.getByRole("menuitem", { name: /Calm/ }));
    expect(run).toHaveBeenCalledExactlyOnceWith("Calm");
  });

  it("finds blocks by name, by what they hold and as blocks while typing", () => {
    const menu = stepMenu("Add a step", steps, vi.fn(), "Nothing fits.", entries());
    const found = (query: string) => menu.search!.results(query).map((item) => `${item.label} · ${item.detail}`);
    expect(found("spikes")).toEqual(["Calm · Block"]);
    expect(found("power")).toEqual(["Power, scaled · Block"]);
    expect(found("block")).toEqual(["Power, scaled · Block", "Calm · Block", "Old step · Block"]);
    expect(found("smooth")).toEqual(["Smooth · Prepare"]);
    // Without blocks the menu is the one it was.
    expect(stepMenu("Add a step", steps, vi.fn(), "Nothing fits.").items.map((item) => item.key)).toEqual(["prepare", "combine"]);
  });
});

describe("blocks in the Add step list", () => {
  const open = (link?: { source: string; target: string }) => {
    const onPlace = vi.fn();
    const onAdd = vi.fn();
    const document = design();
    render(<PipelineToolbox components={components} document={document} link={link} onAdd={onAdd} onPlace={onPlace}
      blocks={blockChoices([scaled, calm, retired], components, (item) => link
        ? insertBlock(document, link, item, components) : placeBlock(document, item, components))} />);
    return { onPlace, onAdd, search: screen.getByRole("searchbox", { name: "Search steps" }) };
  };

  it("lists blocks below the steps and adds the one chosen", () => {
    const { onPlace } = open();
    expect(screen.getAllByRole("heading").map((heading) => heading.textContent)).toContain("Blocks");
    expect(screen.getByRole("button", { name: "Add block Calm" }).textContent).toBe("CalmTake out short spikes");
    const old = screen.getByRole("button", { name: "Add block Old step" }) as HTMLButtonElement;
    expect(old.disabled).toBe(true);
    expect(old.textContent).toContain("Holds a step this version does not offer.");
    fireEvent.click(screen.getByRole("button", { name: "Add block Power, scaled" }));
    expect(onPlace).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ id: "prepare_formula_1" }));
  });

  it("narrows blocks with the steps, and Enter takes the first block that fits when no step matches", () => {
    const { onPlace, onAdd, search } = open({ source: "scale", target: "model" });
    expect(screen.getByRole("button", { name: "Insert block Calm" })).toBeTruthy();
    fireEvent.change(search, { target: { value: "old" } });
    fireEvent.keyDown(search, { key: "Enter" });
    expect(onPlace).not.toHaveBeenCalled();
    fireEvent.change(search, { target: { value: "spikes" } });
    expect(screen.queryByRole("button", { name: "Insert block Power, scaled" })).toBeNull();
    expect(screen.queryByText("No matching steps.")).toBeNull();
    fireEvent.keyDown(search, { key: "Enter" });
    expect(onAdd).not.toHaveBeenCalled();
    expect(onPlace).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ id: "prepare_smooth_1" }));
    fireEvent.change(search, { target: { value: "nothing like it" } });
    expect(screen.getByText("No matching steps.")).toBeTruthy();
  });
});

describe("saving steps as a block", () => {
  const open = (onSave = vi.fn().mockResolvedValue(undefined)) => {
    const onClose = vi.fn();
    render(<PipelineSaveBlock document={design()} components={components} from="power" onSave={onSave} onClose={onClose} />);
    return { onSave, onClose, save: screen.getByRole("button", { name: "Save block" }) as HTMLButtonElement };
  };

  it("holds the step and those after it, up to the one chosen as the last", async () => {
    const { onSave, onClose, save } = open();
    expect(screen.getByText("The block holds 2 steps: Power and Standard scaling.")).toBeTruthy();
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox", { name: "Block name" }), { target: { value: "  Power only " } });
    fireEvent.change(screen.getByRole("textbox", { name: /Description/ }), { target: { value: "Volts times amps" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Last step" }), { target: { value: "0" } });
    expect(screen.getByText("The block holds 1 step: Power.")).toBeTruthy();
    fireEvent.click(save);
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(onSave).toHaveBeenCalledExactlyOnceWith({ name: "Power only", description: "Volts times amps", steps: [POWER] });
  });

  it("stays open with the reason when the library refuses the block", async () => {
    const { onClose, save } = open(vi.fn().mockRejectedValue(new Error("A block named Power already exists. Choose another name.")));
    fireEvent.change(screen.getByRole("textbox", { name: "Block name" }), { target: { value: "Power" } });
    fireEvent.click(save);
    expect((await screen.findByRole("alert")).textContent).toBe("A block named Power already exists. Choose another name.");
    expect(onClose).not.toHaveBeenCalled();
    expect(save.disabled).toBe(false);
  });

  it("offers no last step for a single step", () => {
    render(<PipelineSaveBlock document={design()} components={components} from="scale" onSave={vi.fn()} onClose={vi.fn()} />);
    expect(screen.queryByRole("combobox", { name: "Last step" })).toBeNull();
    expect(screen.getByText("The block holds 1 step: Standard scaling.")).toBeTruthy();
  });
});

describe("the editor's blocks", () => {
  it("loads the library once and lists a saved block by name", async () => {
    const load = vi.spyOn(pipelinesApi, "blocks").mockResolvedValue([calm, scaled]);
    const create = vi.spyOn(pipelinesApi, "createBlock").mockResolvedValue(block("clip", [step("prepare.smooth")]));
    const { result, rerender } = renderHook(() => useBlocks(true));
    await waitFor(() => expect(result.current.blocks).toEqual([calm, scaled]));
    rerender();
    expect(load).toHaveBeenCalledOnce();
    const request = { name: "clip", description: "", steps: [step("prepare.smooth")] };
    await act(() => result.current.save(request));
    expect(create).toHaveBeenCalledExactlyOnceWith(request);
    expect(result.current.blocks.map((item) => item.name)).toEqual(["Calm", "clip", "Power, scaled"]);
  });

  it("offers none where nothing can be changed, or when the library cannot be read", async () => {
    const load = vi.spyOn(pipelinesApi, "blocks").mockRejectedValue(new Error("offline"));
    expect(renderHook(() => useBlocks(false)).result.current.blocks).toEqual([]);
    expect(load).not.toHaveBeenCalled();
    const { result } = renderHook(() => useBlocks(true));
    await waitFor(() => expect(load).toHaveBeenCalledOnce());
    expect(result.current.blocks).toEqual([]);
  });
});

describe("the library's blocks", () => {
  it("lists what each block holds and deletes one after asking", async () => {
    vi.spyOn(pipelinesApi, "blocks").mockResolvedValue([calm, scaled]);
    const remove = vi.spyOn(pipelinesApi, "deleteBlock").mockResolvedValue(undefined);
    render(<PipelineBlockLibrary components={components} canEdit />);
    const list = within(await screen.findByRole("list"));
    expect(list.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "CalmTake out short spikes1 stepDelete", "Power, scaledPower, Standard scaling2 stepsDelete",
    ]);
    fireEvent.click(list.getByRole("button", { name: "Delete Calm" }));
    expect(screen.getByText("Services and templates that already hold its steps keep them.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(list.getByRole("button", { name: "Delete Calm" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete block" }));
    await waitFor(() => expect(list.queryByRole("button", { name: "Delete Calm" })).toBeNull());
    expect(remove).toHaveBeenCalledExactlyOnceWith("calm");
    expect(list.getAllByRole("listitem")).toHaveLength(1);
  });

  it("keeps a block the server would not delete and says why", async () => {
    vi.spyOn(pipelinesApi, "blocks").mockResolvedValue([calm]);
    vi.spyOn(pipelinesApi, "deleteBlock").mockRejectedValue(new Error("Pipeline authoring is disabled"));
    render(<PipelineBlockLibrary components={components} canEdit />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete Calm" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete block" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Pipeline authoring is disabled");
    expect(screen.getByRole("button", { name: "Delete Calm" })).toBeTruthy();
  });

  it("only lists blocks for a member who cannot change them, and says when there are none", async () => {
    const load = vi.spyOn(pipelinesApi, "blocks").mockResolvedValue([calm]);
    const view = render(<PipelineBlockLibrary components={components} canEdit={false} />);
    expect(await screen.findByText("Calm")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete Calm" })).toBeNull();
    view.unmount();
    load.mockResolvedValue([]);
    render(<PipelineBlockLibrary components={components} canEdit />);
    expect(await screen.findByText("No blocks saved yet.")).toBeTruthy();
  });

  it("offers to read the library again when that failed", async () => {
    const load = vi.spyOn(pipelinesApi, "blocks").mockRejectedValueOnce(new Error("Library unavailable")).mockResolvedValue([calm]);
    render(<PipelineBlockLibrary components={components} canEdit />);
    expect((await screen.findByRole("alert")).textContent).toContain("Library unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Retry blocks" }));
    expect(await screen.findByText("Calm")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(load).toHaveBeenCalledTimes(2);
  });
});
