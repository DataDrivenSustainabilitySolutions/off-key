import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState, type ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { normalizeCatalog, normalizeDefinition, normalizeLayout } from "@/features/pipelines/contracts";
import { presentGraph } from "@/features/pipelines/graphPresentation";
import { addComponent, lastNode, nodeLabel, removeElements, setNodeLabel, type GraphDocument } from "@/features/pipelines/model";
import type PipelineCanvas from "@/features/pipelines/PipelineCanvas";
import { PipelineWorkbench } from "@/features/pipelines/PipelineWorkbench";
import { switchedOff } from "@/features/pipelines/semantics";
import { switchOff, switchOffBlocker, switchOn, switchSteps } from "@/features/pipelines/stepSwitch";
import { useGraphEditor } from "@/features/pipelines/useGraphEditor";

vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));

// The canvas is stood in for, so a test changes the design the way the canvas reports it.
let canvas: ComponentProps<typeof PipelineCanvas>;
vi.mock("@/features/pipelines/PipelineCanvas", () => ({
  default: (props: ComponentProps<typeof PipelineCanvas>) => { canvas = props; return <div aria-label="Pipeline graph" />; },
}));

const catalog = normalizeCatalog({
  catalog_id: "test", authoring_enabled: true, templates: [], components: [
    { id: "source.aligned", kind: "source", group: "input", label: "Aligned inputs", description: "",
      input_type: null, output_type: "features" },
    { id: "features.passthrough", kind: "transform", group: "route", label: "Pass through", description: "",
      input_type: "features", output_type: "features" },
    { id: "features.scale", kind: "transform", group: "prepare", label: "Scale", description: "",
      input_type: "features", output_type: "features", fields: [{ name: "factor", label: "Factor", type: "number", default: 1 }] },
    { id: "features.merge", kind: "merge", group: "route", label: "Combine", description: "",
      input_type: "features", output_type: "features" },
    { id: "detector:a", kind: "detector", group: "detector", label: "Detector A", description: "",
      input_type: "features", output_type: "scores" },
  ],
});
const { components } = catalog;

/** Input, a scaling step, a step that passes features through as it is, and a detector. */
const design = (): GraphDocument => ({
  definition: normalizeDefinition({
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "scale", kind: "transform", component: "features.scale", params: { factor: 3 } },
      { id: "plain", kind: "transform", component: "features.passthrough" },
      { id: "detector", kind: "detector", component: "detector:a" },
    ],
    edges: [
      { source: "input", target: "scale", order: 0 },
      { source: "scale", target: "plain", order: 0 },
      { source: "plain", target: "detector", order: 0 },
    ],
  }),
  layout: normalizeLayout({ nodes: {
    input: { x: 0, y: 0 }, scale: { x: 288, y: 0 }, plain: { x: 576, y: 0 }, detector: { x: 864, y: 0 },
  } }),
});

const step = (document: GraphDocument, id: string) => document.definition.nodes.find((node) => node.id === id)!;

describe("switching a step off", () => {
  it("leaves a pass-through step in its place and keeps what the step was", () => {
    const before = design();
    const after = switchOff(before, ["scale"], components);
    // The design runs as it reads: the step is a pass-through step with the same id and connections.
    expect(step(after, "scale")).toEqual({ ...step(before, "scale"), component: "features.passthrough", contract_version: 1, params: {} });
    expect(after.definition.edges).toEqual(before.definition.edges);
    expect(after.layout.switched_off).toEqual({ scale: { component: "features.scale", params: { factor: 3 } } });
    expect(after.layout.nodes).toEqual(before.layout.nodes);
    // Nothing of the design it came from was changed.
    expect(before).toEqual(design());
  });

  it("is for steps that change features", () => {
    const document = design();
    expect(switchOffBlocker(document, "scale", components)).toBeUndefined();
    for (const id of ["input", "detector", "plain"])
      expect(switchOffBlocker(document, id, components)).toBe("Only a step that changes features can be switched off.");
    expect(switchOffBlocker(document, "gone", components)).toBe("This step is gone.");
    expect(switchOffBlocker(switchOff(document, ["scale"], components), "scale", components)).toBe("This step is switched off already.");
    // A deployment without the step that stands in cannot switch a step off.
    const without = components.filter((component) => component.id !== "features.passthrough");
    expect(switchOffBlocker(document, "scale", without)).toBe("This deployment cannot pass features through a step.");
    const unavailable = components.map((component) => component.id === "features.passthrough" ? { ...component, unavailable: "Not installed here." } : component);
    expect(switchOffBlocker(document, "scale", unavailable)).toBe("This deployment cannot pass features through a step.");
    // Steps that cannot stand aside stay as they are.
    expect(switchOff(document, ["input", "detector", "plain", "gone"], components)).toBe(document);
    expect(switchOff(document, ["scale"], without)).toBe(document);
  });

  it("comes back on as it was", () => {
    const off = switchOff(design(), ["scale"], components);
    const on = switchOn(off, ["scale", "plain", "detector"]);
    expect(on.definition).toEqual(design().definition);
    expect(on.layout.switched_off).toEqual({});
    // A step that names the version of its contract names it again.
    const versioned = { ...design(), definition: { ...design().definition,
      nodes: design().definition.nodes.map((node) => node.id === "scale" ? { ...node, contract_version: 1 } : node) } };
    const back = switchOn(switchOff(versioned, ["scale"], components), ["scale"]);
    expect(back.definition).toEqual(versioned.definition);
    // A step that is on has nothing to come back to.
    expect(switchOn(on, ["scale", "plain"])).toBe(on);
  });

  it("switches the chosen steps off, and on again once none of them is on", () => {
    const document = design();
    const first = switchSteps(document, ["input", "scale", "plain", "detector"], components)!;
    expect(first).toMatchObject({ ids: ["scale"], off: true });
    expect(switchedOff(first.document.layout, step(first.document, "scale"))).toBeTruthy();
    const second = switchSteps(first.document, ["input", "scale", "plain", "detector"], components)!;
    expect(second).toMatchObject({ ids: ["scale"], off: false });
    expect(second.document.definition).toEqual(document.definition);
    expect(switchSteps(document, ["input", "plain", "detector"], components)).toBeUndefined();
  });

  it("does not take a step for switched off that is something else again", () => {
    // What a layout remembers counts only while the step is the pass-through step that stands in.
    const stale: GraphDocument = { ...design(), layout: { ...design().layout,
      switched_off: { scale: { component: "features.other", contract_version: 1, params: {} } } } };
    expect(switchedOff(stale.layout, step(stale, "scale"))).toBeUndefined();
    expect(switchedOff(stale.layout, step(stale, "plain"))).toBeUndefined();
    expect(switchedOff(undefined, step(stale, "plain"))).toBeUndefined();
    expect(switchOn(stale, ["scale"])).toBe(stale);
    expect(presentGraph(stale, components).nodes[1]!.data).toMatchObject({ label: "Scale", off: false });
  });

  it("forgets what a step was when the step is removed", () => {
    const off = switchOff(design(), ["scale"], components);
    expect(removeElements(off, { nodeIds: ["plain"] }).layout.switched_off).toHaveProperty("scale");
    expect(removeElements(off, { nodeIds: ["scale"] }).layout.switched_off).toEqual({});
    // A design that never switched a step off gains no list of them.
    expect(removeElements(design(), { nodeIds: ["scale"] }).layout).not.toHaveProperty("switched_off");
  });
});

describe("a step that is switched off, on the canvas", () => {
  it("keeps its name and family, and says that it is off", () => {
    const off = switchOff(design(), ["scale"], components);
    expect(nodeLabel(step(off, "scale"), components, off.layout)).toBe("Scale");
    expect(nodeLabel(step(off, "scale"), components, setNodeLabel(off, "scale", "Triple").layout)).toBe("Triple");
    const [, scale, plain] = presentGraph(off, components).nodes;
    const on = presentGraph(design(), components).nodes[1]!;
    expect(scale!.data).toMatchObject({ label: "Scale", operation: "Scale", family: on.data.family, off: true,
      summary: "Switched off", chips: undefined, available: true, inputType: "features", outputType: "features" });
    expect(scale!.ariaLabel).toBe(on.ariaLabel);
    // A pass-through step of the design's own is a step like any other.
    expect(plain!.data).toMatchObject({ label: "Pass through", off: false });
    expect(plain!.data.summary).not.toBe("Switched off");
  });

  it("counts as what it was when the next step of its kind is numbered", () => {
    const off = switchOff(design(), ["scale"], components);
    const scale = components.find((component) => component.id === "features.scale")!;
    const pass = components.find((component) => component.id === "features.passthrough")!;
    const added = addComponent(off, scale);
    expect(added.layout.nodes[lastNode(added)]!.label).toBe("Scale 2");
    // And not as the step that stands in for it.
    const passed = addComponent(off, pass);
    expect(passed.layout.nodes[lastNode(passed)]!.label).toBe("Pass through 2");
  });

  it("is named by its id when the deployment no longer offers what it was", () => {
    const off = switchOff(design(), ["scale"], components);
    const fewer = components.filter((component) => component.id !== "features.scale");
    expect(presentGraph(off, fewer).nodes[1]!.data).toMatchObject({ label: "features.scale", operation: "features.scale", off: true, available: true });
  });
});

describe("a step that is switched off, in its settings", () => {
  function Composer({ readOnly = false }: { readOnly?: boolean }) {
    const [document, setDocument] = useState(() => switchOff(design(), ["scale"], components));
    const editor = useGraphEditor({ document, onChange: setDocument, components });
    return <PipelineWorkbench catalog={catalog} document={document} selected={editor.selected} onSelect={editor.select}
      onChange={editor.commit} onAdd={editor.add} readOnly={readOnly} />;
  }
  const said = () => screen.queryByText(/This step is switched off\. Features pass through it unchanged, and its settings are kept\./);

  it("says so in place of its settings, and switches on with them", () => {
    render(<Composer />);
    act(() => canvas.onSelect("scale"));
    expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "Selected step" }).selectedOptions[0]!.textContent).toContain("Scale");
    expect(said()).not.toBeNull();
    expect(screen.queryByLabelText("Factor")).toBeNull();
    // Its title is its own, and the name of what it was stands where a title would.
    expect(screen.getByLabelText<HTMLInputElement>("Step title").placeholder).toBe("Scale");

    fireEvent.click(screen.getByRole("button", { name: "Switch on" }));
    expect(said()).toBeNull();
    expect(screen.getByLabelText<HTMLInputElement>("Factor").value).toBe("3");
    expect(canvas.document.definition).toEqual(design().definition);
    expect(screen.queryByRole("button", { name: "Switch on" })).toBeNull();
  });

  it("only says so where the design is shown and not edited", () => {
    render(<Composer readOnly />);
    act(() => canvas.onSelect("scale"));
    expect(said()).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Switch on" })).toBeNull();
  });
});
