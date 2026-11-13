import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  normalizeCatalog,
  normalizeDefinition,
  normalizeLayout,
} from "@/features/pipelines/contracts";
import { pipelinesApi } from "@/features/pipelines/api";
import { placeBlock } from "@/features/pipelines/blocks";
import {
  addBlocker,
  freePosition,
  setNodeLabel,
  type GraphDocument,
} from "@/features/pipelines/model";
import { PipelineDesignSettings } from "@/features/pipelines/PipelineDesignSettings";
import { PipelineToolbox } from "@/features/pipelines/PipelineToolbox";
import { NODE_SIZE } from "@/features/pipelines/semantics";
import { addReading, featureName, selectReadings, targetInputs } from "@/features/pipelines/slots";
import { startupEstimate } from "@/features/pipelines/startup";
import { useGraphEditor } from "@/features/pipelines/useGraphEditor";
import type { MonitoringTarget } from "@/domain/monitoring/serviceModel";
import { clearNavigationDrafts, useNavigationDraft } from "@/lib/navigation-draft";

vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));

const catalog = normalizeCatalog({
  catalog_id: "test", authoring_enabled: true, templates: [], components: [
    { id: "source.aligned", kind: "source", group: "input", label: "Aligned inputs", description: "",
      input_type: null, output_type: "features" },
    { id: "features.passthrough", kind: "transform", group: "route", label: "Pass through", description: "",
      input_type: "features", output_type: "features" },
    { id: "detector:a", kind: "detector", group: "detector", label: "Detector A", description: "",
      input_type: "features", output_type: "scores" },
    { id: "detector:static", kind: "detector", group: "detector", label: "Static detector", description: "",
      input_type: "features", output_type: "p_values" },
  ],
});
const components = catalog.components;
const passthrough = components.find((item) => item.id === "features.passthrough")!;

const pipeline = (): GraphDocument => ({
  definition: normalizeDefinition({
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "detector", kind: "detector", component: "detector:a" },
    ],
    edges: [{ source: "input", target: "detector", order: 0 }],
  }),
  layout: normalizeLayout({ nodes: { input: { x: 0, y: 0 }, detector: { x: 288, y: 0 } } }),
});

const passes = { id: "passes", name: "Pass twice", description: "", created_at: "2026-11-12T09:00:00Z", steps: [
  { component: "features.passthrough", contract_version: 1, params: {}, label: "First pass" },
  { component: "features.passthrough", contract_version: 1, params: {} },
] };

beforeEach(() => {
  clearNavigationDrafts();
  // The editor reads the block library when it opens; without a test's own answer it never arrives.
  vi.spyOn(pipelinesApi, "blocks").mockReturnValue(new Promise(() => {}));
});

describe("component placement", () => {
  it("places a new component beside its anchor without covering another card", () => {
    const document = pipeline();
    const position = freePosition(document, "input");
    // The slot right of the input is taken by the detector, so the card moves down.
    expect(position.x).toBeGreaterThanOrEqual(NODE_SIZE.width);
    const overlaps = Object.values(document.layout.nodes).some((box) =>
      box.x < position.x + NODE_SIZE.width && position.x < box.x + NODE_SIZE.width
      && box.y < position.y + NODE_SIZE.height && position.y < box.y + NODE_SIZE.height);
    expect(overlaps).toBe(false);
    expect(freePosition(document).x).toBeGreaterThan(288);
  });

  it("explains why a component cannot be added instead of hiding it", () => {
    const definition = pipeline().definition;
    // A second detector comes from the first one's settings, which connect it.
    expect(addBlocker(definition, components.find((item) => item.id === "detector:a")!))
      .toBe("Add another detector from a detector's settings.");
    // That holds for a detector that learns differently too: a design has no strategy to break.
    expect(addBlocker(definition, components.find((item) => item.id === "detector:static")!))
      .toBe("Add another detector from a detector's settings.");
    expect(addBlocker(definition, passthrough)).toBeUndefined();
  });
});

function useEditor() {
  const [document, setDocument] = useNavigationDraft("composer-test:document", pipeline);
  const editor = useGraphEditor({
    document, onChange: setDocument, components, historyKey: "composer-test:history",
  });
  return { ...editor, document };
}

describe("graph editing", () => {
  it("merges consecutive edits of one field into a single undo step", () => {
    const { result } = renderHook(() => useEditor());
    const title = (label: string) => setNodeLabel(result.current.document, "input", label);
    const titled = () => result.current.document.definition.nodes.find((node) => node.id === "input")?.label;
    for (const label of ["P", "Pu", "Pump"]) act(() => result.current.commit(title(label), "title:input"));
    act(() => result.current.commit({ ...result.current.document,
      layout: { ...result.current.document.layout, nodes: { ...result.current.document.layout.nodes,
        detector: { x: 400, y: 0 } } } }));
    act(() => result.current.undo());
    expect(titled()).toBe("Pump");
    act(() => result.current.undo());
    expect(titled()).toBeUndefined();
    expect(result.current.canUndo).toBe(false);
  });

  it("clears the selection when the selected component is removed", () => {
    const { result } = renderHook(() => useEditor());
    act(() => result.current.select("detector"));
    expect(result.current.selected).toBe("detector");
    act(() => result.current.commit({
      ...result.current.document,
      definition: { ...result.current.document.definition,
        nodes: result.current.document.definition.nodes.filter((node) => node.id !== "detector"), edges: [] },
    }));
    expect(result.current.selected).toBeUndefined();
  });

  it("places a new component beside the selected one and asks the canvas to reveal it", () => {
    const { result } = renderHook(() => useEditor());
    act(() => result.current.select("input"));
    act(() => result.current.add("features.passthrough"));
    expect(result.current.selected).toBe("features_passthrough_1");
    expect(result.current.reveal?.id).toBe("features_passthrough_1");
    expect(result.current.document.layout.nodes.features_passthrough_1?.x).toBeGreaterThan(0);
    // Connections stay explicit: a palette click never rewires the graph.
    expect(result.current.document.definition.edges).toEqual(pipeline().definition.edges);
  });

  it("takes a block's steps as one change, selecting and revealing the first of them", () => {
    const { result } = renderHook(() => useEditor());
    const placed = placeBlock(result.current.document, passes, components);
    if ("blocked" in placed) throw new Error(placed.blocked);
    act(() => result.current.place(placed));
    expect(result.current.selected).toBe("features_passthrough_1");
    expect(result.current.reveal?.id).toBe("features_passthrough_1");
    expect(result.current.document.definition.nodes).toHaveLength(4);
    act(() => result.current.undo());
    expect(result.current.document.definition.nodes).toHaveLength(2);
    expect(result.current.canUndo).toBe(false);
  });

  it("offers saved blocks under Add step and hands their steps to the editor", async () => {
    const { PipelineWorkbench } = await import("@/features/pipelines/PipelineWorkbench");
    vi.mocked(pipelinesApi.blocks).mockResolvedValue([passes]);
    const onPlace = vi.fn();
    const props = { catalog, document: pipeline(), onSelect: () => {}, onChange: () => {}, onAdd: () => {}, onPlace };
    const view = render(<PipelineWorkbench {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Add step" }));
    const steps = within(screen.getByRole("dialog", { name: "Add a step" }));
    fireEvent.click(await steps.findByRole("button", { name: "Add block Pass twice" }));
    expect(onPlace).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ id: "features_passthrough_1" }));
    const placed = onPlace.mock.calls[0]![0].document as GraphDocument;
    expect(placed.definition.nodes.find((item) => item.id === "features_passthrough_1")?.label).toBe("First pass");
    expect(placed.definition.edges).toContainEqual({ source: "features_passthrough_1", target: "features_passthrough_2", order: 0 });
    expect(screen.queryByRole("dialog", { name: "Add a step" })).toBeNull();
    // A design that is only shown offers no steps and reads no library.
    view.unmount();
    vi.mocked(pipelinesApi.blocks).mockClear();
    render(<PipelineWorkbench {...props} readOnly />);
    expect(screen.queryByRole("button", { name: "Add step" })).toBeNull();
    expect(pipelinesApi.blocks).not.toHaveBeenCalled();
  });

  it("undoes with Ctrl+Z outside text fields only", async () => {
    const { PipelineWorkbench } = await import("@/features/pipelines/PipelineWorkbench");
    let undone = 0;
    render(<PipelineWorkbench catalog={catalog} document={pipeline()} onSelect={() => {}}
      onChange={() => {}} onAdd={() => {}} onUndo={() => { undone++; }} onRedo={() => {}} settings={<input aria-label="Name" />} />);
    fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
    expect(undone).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Service settings" }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Name" }), { key: "z", ctrlKey: true });
    expect(undone).toBe(1);
  });

  it("says when the first alarm can come and offers another check when one fails", async () => {
    const { PipelineWorkbench } = await import("@/features/pipelines/PipelineWorkbench");
    const valid = { valid: true, definition: pipeline().definition, issues: [], features: {}, provenance_complete: true };
    const startup = startupEstimate(pipeline().definition, [1, 0.5]);
    let retried = 0;
    const props = { catalog, document: pipeline(), onSelect: () => {}, onChange: () => {}, onAdd: () => {}, startup,
      onRetryValidation: () => { retried++; } };
    const view = render(<PipelineWorkbench {...props} validation={valid} />);
    const chip = screen.getByRole("button", { name: "Design is complete, first alarm after about 26 min" });
    fireEvent.click(chip);
    expect(screen.getByText(/1,200 to learn and 360 to calibrate\. At one observation every 1 s, that is about 26 min\./)).toBeTruthy();
    view.rerender(<PipelineWorkbench {...props} validationError="Validation service unavailable" />);
    expect(screen.getByRole("button", { name: "Design not checked" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Validation service unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(retried).toBe(1);
  });
});

describe("service settings", () => {
  it("keeps the last valid learning window while a number is retyped", () => {
    const changes: GraphDocument[] = [];
    render(<PipelineDesignSettings document={pipeline()} readOnly={false}
      onChange={(document) => { changes.push(document); }} />);
    const field = screen.getByRole("spinbutton", { name: "Calibration observations" });
    fireEvent.change(field, { target: { value: "" } });
    expect((field as HTMLInputElement).value).toBe("");
    expect(screen.getByText(/Enter a number/)).toBeTruthy();
    expect(changes).toHaveLength(0);
    fireEvent.change(field, { target: { value: "500" } });
    expect(changes[changes.length - 1]?.definition.settings.calibration_window_size).toBe(500);
  });

  it("names one slot per enabled reading after the reading", () => {
    const target = { id: "a", label: "Charger A", inputs: [
      { stream: { id: "v", label: "DC voltage", unit: "V" }, binding: { policy: { mode: "always" } } },
      { stream: { id: "c", label: "Current", unit: "A" }, binding: { policy: { mode: "always" } } },
      { stream: { id: "x", label: "Off", unit: null }, binding: { policy: { mode: "off" } } },
    ] } as unknown as MonitoringTarget;
    const inputs = targetInputs(target)!;
    expect(inputs.slots).toEqual([
      { id: "dc_voltage", label: "DC voltage", unit: "V" },
      { id: "current", label: "Current", unit: "A" },
    ]);
    expect(inputs.bindings).toEqual({ dc_voltage: "v", current: "c" });
  });

  it("turns any reading label into a valid, readable feature name", () => {
    expect(featureName("DC voltage")).toBe("dc_voltage");
    expect(featureName("  Température extérieure (°C) ")).toBe("temperature_exterieure_c");
    expect(featureName("1st phase")).toBe("reading_1st_phase");
    expect(featureName("电流")).toBe("reading");
    expect(featureName("x".repeat(80))).toHaveLength(48);
    for (const label of ["DC voltage", "1st phase", "电流", "a--b", "x".repeat(80)])
      expect(featureName(label)).toMatch(/^[A-Za-z][A-Za-z0-9_-]{0,99}$/);
  });

  it("keeps exact reading identities when labels repeat, and preserves slot IDs through subset changes", () => {
    const target = { inputs: ["ac1", "ac2", "ac3", "ac4"].map((id) => ({
      stream: { id, label: "Current", unit: "A" }, binding: { policy: { mode: "original" } },
    })) } as MonitoringTarget;
    const all = targetInputs(target)!;
    expect(all.slots.map((slot) => slot.id)).toEqual(["current", "current_2", "current_3", "current_4"]);
    expect(Object.values(all.bindings)).toEqual(["ac1", "ac2", "ac3", "ac4"]);
    const subset = selectReadings(target, all.slots, all.bindings, ["ac1", "ac3"]);
    expect(subset.slots).toEqual([all.slots[0], all.slots[2]]);
    const restored = selectReadings(target, subset.slots, subset.bindings, ["ac1", "ac2", "ac3"]);
    expect(restored.slots.find((slot) => restored.bindings[slot.id] === "ac2")).toEqual(all.slots[1]);
    const cleared = selectReadings(target, restored.slots, restored.bindings, []);
    expect(cleared.slots).toEqual([]);
    expect(selectReadings(target, cleared.slots, cleared.bindings, ["ac3"]).slots).toEqual([all.slots[2]]);
    const extra = { ...target.inputs[0]!, stream: { ...target.inputs[0]!.stream, id: "extra" } };
    const added = addReading(subset.slots, subset.bindings, extra);
    expect(added.slots[added.slots.length - 1]?.id).not.toBe(all.slots[1]!.id);
  });

  it("bounds initial and expanded selections to the supported 100 readings", () => {
    const target = { inputs: Array.from({ length: 101 }, (_, index) => ({
      stream: { id: `ac${index}`, label: `Current ${index}` }, binding: { policy: { mode: "original" } },
    })) } as MonitoringTarget;
    const all = targetInputs(target)!;
    expect(all.slots).toHaveLength(100);
    expect(addReading(all.slots, all.bindings, target.inputs[100]!).slots).toHaveLength(100);
    expect(selectReadings(target, [], {}, target.inputs.map((input) => input.stream.id)).slots).toHaveLength(100);
  });
});

describe("component menu", () => {
  it("leaves out one-per-pipeline steps that are present and opens them instead", () => {
    let selected = "";
    render(<PipelineToolbox components={components} document={pipeline()} onAdd={() => {}}
      onSelect={(id) => { selected = id; }} />);
    expect(screen.queryByRole("button", { name: "Add Detector A" })).toBeNull();
    expect(screen.getByText(/The detector is already in this pipeline\. Open it to change it\./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Select Detector A" }));
    expect(selected).toBe("detector");
  });

  it("groups steps by what they do, with one line each, and adds from the keyboard", () => {
    const added: string[] = [];
    // Group and description are the catalog's own.
    const listed = [
      ["adaptive.standard_scaler", "normalize", "Center and scale with running statistics."],
      ["adaptive.uncentered_pca", "reduce", "Keep the main directions, updated as data arrives."],
      ["features.select", "route", "Keep only the chosen features."],
    ] as const;
    const steps = [...components, ...normalizeCatalog({ catalog_id: "steps", authoring_enabled: true, templates: [],
      components: listed.map(([id, group, description]) => ({
        id, kind: "transform" as const, group, label: id, description,
        input_type: "features" as const, output_type: "features" as const })),
    }).components];
    render(<PipelineToolbox components={steps} document={pipeline()} onAdd={(id) => added.push(id)} />);
    expect(screen.getAllByRole("heading").map((heading) => heading.textContent)).toEqual(["Normalize", "Reduce", "Route"]);
    expect(screen.getByRole("button", { name: "Add adaptive.standard_scaler" }).getAttribute("aria-describedby")).toBeTruthy();
    expect(screen.getByText("Center and scale with running statistics.")).toBeTruthy();
    const search = screen.getByRole("searchbox", { name: "Search steps" });
    search.focus();
    fireEvent.keyDown(search, { key: "ArrowDown" });
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Add adaptive.standard_scaler");
    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Add adaptive.uncentered_pca");
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Add features.select");
    fireEvent.change(search, { target: { value: "main directions" } });
    fireEvent.keyDown(search, { key: "Enter" });
    expect(added).toEqual(["adaptive.uncentered_pca"]);
  });

  it("lists only the steps that fit a connection when inserting on it", () => {
    const added: string[] = [];
    render(<PipelineToolbox components={components} document={pipeline()}
      link={{ source: "input", target: "detector" }} onAdd={(id) => added.push(id)} />);
    // One-per-design components and other strategies' components never fit a wire.
    expect(screen.getAllByRole("button").map((button) => button.getAttribute("aria-label")))
      .toEqual(["Insert Pass through"]);
    expect(screen.getByRole("button", { name: "Insert Pass through" }).getAttribute("draggable")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "Insert Pass through" }));
    expect(added).toEqual(["features.passthrough"]);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search steps" }), { target: { value: "scaling" } });
    expect(screen.getByText("No matching steps.")).toBeTruthy();
  });
});
