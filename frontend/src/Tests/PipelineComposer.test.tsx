import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  normalizeCatalog,
  normalizeDefinition,
  normalizeLayout,
} from "@/features/pipelines/contracts";
import { createCreationSession, type CreationDraft } from "@/features/pipelines/creationSession";
import {
  addBlocker,
  freePosition,
  type GraphDocument,
} from "@/features/pipelines/model";
import { PipelineDesignSettings } from "@/features/pipelines/PipelineDesignSettings";
import { PipelineToolbox } from "@/features/pipelines/PipelineToolbox";
import { routeConnections } from "@/features/pipelines/routing";
import { NODE_SIZE } from "@/features/pipelines/semantics";
import { addReading, selectReadings, targetInputs } from "@/features/pipelines/slots";
import { useGraphEditor } from "@/features/pipelines/useGraphEditor";
import type { MonitoringTarget } from "@/domain/monitoring/serviceModel";
import { clearNavigationDrafts, storeDraft, useNavigationDraft } from "@/lib/navigation-draft";

vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));

const catalog = normalizeCatalog({
  catalog_id: "test", authoring_enabled: true, templates: [], components: [
    { id: "source.aligned", kind: "source", label: "Aligned inputs", description: "",
      strategies: ["adaptive_stream"], input_type: null, output_type: "features" },
    { id: "features.passthrough", kind: "transform", label: "Pass through", description: "",
      strategies: ["adaptive_stream"], input_type: "features", output_type: "features" },
    { id: "detector:a", kind: "detector", label: "Detector A", description: "",
      strategies: ["adaptive_stream"], input_type: "features", output_type: "scores" },
    { id: "detector:static", kind: "detector", label: "Static detector", description: "",
      strategies: ["static_baseline"], input_type: "features", output_type: "p_values" },
  ],
});
const components = catalog.components;
const passthrough = components.find((item) => item.id === "features.passthrough")!;

const pipeline = (): GraphDocument => ({
  definition: normalizeDefinition({
    strategy: "adaptive_stream",
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "detector", kind: "detector", component: "detector:a" },
    ],
    edges: [{ source: "input", target: "detector", order: 0 }],
  }),
  layout: normalizeLayout({ nodes: { input: { x: 0, y: 0 }, detector: { x: 288, y: 0 } } }),
});

beforeEach(() => { clearNavigationDrafts(); });

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
    expect(addBlocker(definition, components.find((item) => item.id === "detector:a")!))
      .toBe("A design has one of these.");
    expect(addBlocker(definition, components.find((item) => item.id === "detector:static")!))
      .toBe("Not available for this strategy.");
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
    const title = (label: string) => ({
      ...result.current.document,
      layout: { ...result.current.document.layout, nodes: {
        ...result.current.document.layout.nodes,
        input: { ...result.current.document.layout.nodes.input!, label },
      } },
    });
    for (const label of ["P", "Pu", "Pump"]) act(() => result.current.commit(title(label), "title:input"));
    act(() => result.current.commit({ ...result.current.document,
      layout: { ...result.current.document.layout, nodes: { ...result.current.document.layout.nodes,
        detector: { x: 400, y: 0 } } } }));
    act(() => result.current.undo());
    expect(result.current.document.layout.nodes.input?.label).toBe("Pump");
    act(() => result.current.undo());
    expect(result.current.document.layout.nodes.input?.label).toBeUndefined();
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

  it("undoes with Ctrl+Z outside text fields only", async () => {
    const { PipelineWorkbench } = await import("@/features/pipelines/PipelineWorkbench");
    let undone = 0;
    render(<PipelineWorkbench catalog={catalog} document={pipeline()} onSelect={() => {}}
      onChange={() => {}} onAdd={() => {}} onUndo={() => { undone++; }} onRedo={() => {}} settings={<input aria-label="Name" />} />);
    fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
    expect(undone).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Learning settings" }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Name" }), { key: "z", ctrlKey: true });
    expect(undone).toBe(1);
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

  it("derives one uniquely named slot per enabled reading", () => {
    const target = { id: "a", label: "Charger A", inputs: [
      { stream: { id: "v", label: "Voltage", unit: "V" }, binding: { policy: { mode: "always" } } },
      { stream: { id: "c", label: "Current", unit: "A" }, binding: { policy: { mode: "always" } } },
      { stream: { id: "x", label: "Off", unit: null }, binding: { policy: { mode: "off" } } },
    ] } as unknown as MonitoringTarget;
    const inputs = targetInputs(target, [{ id: "input_2", label: "Value", unit: null }])!;
    expect(inputs.slots).toEqual([
      { id: "input_2", label: "Voltage", unit: "V" },
      { id: "input_3", label: "Current", unit: "A" },
    ]);
    expect(inputs.bindings).toEqual({ input_2: "v", input_3: "c" });
  });

  it("keeps exact reading identities when labels repeat, and preserves slot IDs through subset changes", () => {
    const target = { inputs: ["ac1", "ac2", "ac3", "ac4"].map((id) => ({
      stream: { id, label: "Current", unit: "A" }, binding: { policy: { mode: "original" } },
    })) } as MonitoringTarget;
    const all = targetInputs(target, [{ id: "value", label: "Value" }])!;
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
    const all = targetInputs(target, [])!;
    expect(all.slots).toHaveLength(100);
    expect(addReading(all.slots, all.bindings, target.inputs[100]!).slots).toHaveLength(100);
    expect(selectReadings(target, [], {}, target.inputs.map((input) => input.stream.id)).slots).toHaveLength(100);
  });
});

describe("component menu", () => {
  it("offers to select a one-per-design component that is already present", () => {
    let selected = "";
    render(<PipelineToolbox catalog={catalog} document={pipeline()} onAdd={() => {}}
      onSelect={(id) => { selected = id; }} />);
    fireEvent.click(screen.getByRole("button", { name: "Select Detector A" }));
    expect(selected).toBe("detector");
    expect(screen.getByText(/Select it to change the detector model/)).toBeTruthy();
  });
});

describe("creation drafts", () => {
  const initial = (): CreationDraft => ({ document: pipeline(), name: "", description: "" });

  it("restores an unsaved design after a reload and can discard it", () => {
    const edited = { ...initial(), name: "Machine health" };
    storeDraft("creation:reload", edited);
    const session = createCreationSession(initial(), "creation:reload");
    expect(session.restored).toBe(true);
    expect(session.getSnapshot().draft.name).toBe("Machine health");
    session.discard(initial());
    expect(session.getSnapshot().draft.name).toBe("");
    expect(createCreationSession(initial(), "creation:reload").restored).toBe(false);
  });
});

describe("drag routing", () => {
  it("reuses settled routes for links that do not touch the moving component", () => {
    const boxes = [
      { id: "a", x: 0, y: 0, ...NODE_SIZE }, { id: "b", x: 400, y: 0, ...NODE_SIZE },
      { id: "c", x: 0, y: 400, ...NODE_SIZE }, { id: "d", x: 400, y: 400, ...NODE_SIZE },
    ];
    const edges = [{ source: "a", target: "b" }, { source: "c", target: "d" }];
    const settled = routeConnections(boxes, edges);
    const moved = routeConnections(boxes.map((box) => box.id === "d" ? { ...box, y: 480 } : box), edges,
      { previous: settled, changed: new Set(["d"]) });
    expect(moved.get(JSON.stringify(["a", "b"]))).toBe(settled.get(JSON.stringify(["a", "b"])));
    expect(moved.get(JSON.stringify(["c", "d"]))).not.toBe(settled.get(JSON.stringify(["c", "d"])));
  });

  it("reroutes an unrelated link when the moving component lands on it", () => {
    const boxes = [
      { id: "a", x: 0, y: 0, ...NODE_SIZE }, { id: "b", x: 800, y: 0, ...NODE_SIZE },
      { id: "obstacle", x: 400, y: 400, ...NODE_SIZE },
    ];
    const edges = [{ source: "a", target: "b" }];
    const key = JSON.stringify(["a", "b"]);
    const settled = routeConnections(boxes, edges);
    const moved = routeConnections(boxes.map((box) => box.id === "obstacle" ? { ...box, y: 0 } : box), edges,
      { previous: settled, changed: new Set(["obstacle"]) });
    expect(moved.get(key)).not.toBe(settled.get(key));
    expect(moved.get(key)?.blocked).toBe(false);
    expect(moved.get(key)?.points.some((point) => point.y !== NODE_SIZE.height / 2)).toBe(true);
  });
});
