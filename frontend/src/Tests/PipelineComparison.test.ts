// @vitest-environment node
import { describe, expect, it } from "vitest";
import { compareDesigns, comparisonSummary } from "@/features/pipelines/comparison";
import { normalizeCatalog, normalizeDefinition, normalizeLayout } from "@/features/pipelines/contracts";
import { presentGraph } from "@/features/pipelines/graphPresentation";
import { addAfter, removeNode, setNodeLabel, setNodeParams, type GraphDocument } from "@/features/pipelines/model";
import { switchOff } from "@/features/pipelines/stepSwitch";

const { components } = normalizeCatalog({
  catalog_id: "test", authoring_enabled: true, templates: [], components: [
    { id: "source.aligned", kind: "source", group: "input", label: "Aligned inputs", description: "",
      input_type: null, output_type: "features" },
    { id: "features.passthrough", kind: "transform", group: "route", label: "Pass through", description: "",
      input_type: "features", output_type: "features" },
    { id: "features.scale", kind: "transform", group: "prepare", label: "Scale", description: "",
      input_type: "features", output_type: "features", fields: [
        { name: "factor", label: "Factor", type: "number", default: 1 },
        { name: "clip", label: "Clip", type: "boolean", default: false },
        { name: "mapping", label: "Mapping", type: "rename", default: {} },
      ] },
    { id: "features.smooth", kind: "transform", group: "prepare", label: "Smooth", description: "",
      input_type: "features", output_type: "features" },
    { id: "detector:a", kind: "detector", group: "detector", label: "Detector A", description: "",
      input_type: "features", output_type: "scores" },
    { id: "detector:b", kind: "detector", group: "detector", label: "Detector B", description: "",
      input_type: "features", output_type: "scores" },
  ],
});

/** What runs now: input, a scaling step, a smoothing step and a detector. */
const running = (): GraphDocument => ({
  definition: normalizeDefinition({
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "scale", kind: "transform", component: "features.scale", params: { factor: 3 } },
      { id: "smooth", kind: "transform", component: "features.smooth", label: "Calm" },
      { id: "detector", kind: "detector", component: "detector:a" },
    ],
    edges: [
      { source: "input", target: "scale", order: 0 },
      { source: "scale", target: "smooth", order: 0 },
      { source: "smooth", target: "detector", order: 0 },
    ],
    settings: { training_window_size: 300, calibration_window_size: 100, seed: 42 },
  }),
  layout: normalizeLayout({ nodes: {
    input: { x: 0, y: 0 }, scale: { x: 288, y: 0 }, smooth: { x: 576, y: 0 }, detector: { x: 864, y: 0 },
  } }),
});
const node = (document: GraphDocument, id: string) => document.definition.nodes.find((item) => item.id === id)!;
const changed = (design: GraphDocument) => compareDesigns(running(), design, components);

describe("a design beside the one that runs", () => {
  it("finds nothing to look at in the same design, however its settings are written", () => {
    const design = running();
    // A default that is spelled out is the default all the same, and a moved card is the same step.
    node(design, "scale").params = { factor: 3, clip: false, mapping: {} };
    design.layout.nodes.scale = { x: 300, y: 120 };
    const comparison = changed(design);
    expect(comparison).toEqual({ steps: {}, removed: [], service: [] });
    expect(comparisonSummary(comparison)).toBeUndefined();
  });

  it("says which settings of a step changed, and from what", () => {
    const design = setNodeParams(running(), "scale", { factor: 0.25, clip: true, mapping: { value: "volts" }, extra_one: 2 });
    expect(changed(design).steps).toEqual({
      scale: { kind: "changed", detail: "Factor 0.25, was 3. Clip on, was off. Mapping changed. Extra one 2, was none." },
    });
  });

  it("keeps the digits that tell a small rate or a quantile near one apart", () => {
    const rate = setNodeParams(running(), "scale", { factor: 0.0001 });
    const was = { ...running(), definition: { ...running().definition,
      nodes: running().definition.nodes.map((item) => item.id === "scale" ? { ...item, params: { factor: 0.00001 } } : item) } };
    expect(compareDesigns(was, rate, components).steps.scale?.detail).toBe("Factor 0.0001, was 0.00001.");
    const near = setNodeParams(running(), "scale", { factor: 0.99999 });
    const before = setNodeParams(running(), "scale", { factor: 0.9999 });
    expect(compareDesigns(before, near, components).steps.scale?.detail).toBe("Factor 0.99999, was 0.9999.");
  });

  it("marks new steps and names the ones that went", () => {
    const smooth = components.find((component) => component.id === "features.smooth")!;
    const added = addAfter(running(), "scale", smooth, components)!;
    const design = removeNode(added.document, "smooth");
    const comparison = changed(design);
    expect(comparison.steps[added.id]).toEqual({ kind: "new", detail: "The running design has no such step." });
    // The removed step goes by the title it ran under.
    expect(comparison.removed).toEqual(["Calm"]);
    expect(comparisonSummary(comparison)).toBe("1 new step, 1 changed step, 1 removed (Calm).");
    // Removing a step takes its connections with it, so the detector takes from nothing.
    expect(comparison.steps.detector).toEqual({ kind: "changed", detail: "Connected differently." });
  });

  it("leaves the step behind a new one alone, and says when a step takes from elsewhere", () => {
    const smooth = components.find((component) => component.id === "features.smooth")!;
    const added = addAfter(running(), "input", smooth, components)!;
    // The new step is the change: the scaling step behind it is the step it was.
    expect(Object.keys(changed(added.document).steps)).toEqual([added.id]);
    const rewired = running();
    rewired.definition.edges = rewired.definition.edges.map((edge) => edge.target === "detector" ? { ...edge, source: "scale" } : edge);
    expect(changed(rewired).steps).toEqual({ detector: { kind: "changed", detail: "Connected differently." } });
    // A step that went leaves no card, so the step that took its place behind the others says that it went.
    const bridged = removeNode(running(), "smooth");
    bridged.definition.edges = [...bridged.definition.edges, { source: "scale", target: "detector", order: 0 }];
    expect(changed(bridged)).toMatchObject({
      steps: { detector: { kind: "changed", detail: "No longer follows Calm." } }, removed: ["Calm"],
    });
  });

  it("tells another component, a title and a switch apart", () => {
    const design = setNodeLabel(running(), "smooth", "");
    node(design, "detector").component = "detector:b";
    expect(changed(design).steps).toEqual({
      smooth: { kind: "changed", detail: "Title was “Calm”." },
      detector: { kind: "changed", detail: "Was Detector A." },
    });
    expect(changed(setNodeLabel(running(), "scale", "Volts")).steps.scale?.detail).toBe("Has a title.");
    const off = switchOff(running(), ["scale"], components);
    expect(changed(off).steps).toEqual({ scale: { kind: "changed", detail: "Switched off." } });
    // Against a design that runs with the step off, the step that is on again is the change.
    expect(compareDesigns(off, running(), components).steps).toEqual({ scale: { kind: "changed", detail: "Switched on." } });
  });

  it("says what differs beside the steps", () => {
    const design = running();
    design.definition.input_slots = [{ id: "input_2", label: "Current" }, { id: "input_3", label: "Flow" }];
    design.definition.settings = { ...design.definition.settings, training_window_size: 600, seed: null };
    const comparison = changed(design);
    expect(comparison.service).toEqual([
      "2 inputs added", "1 input removed", "Training observations 600, was 300", "Random seed none, was 42",
    ]);
    expect(comparisonSummary(comparison))
      .toBe("2 inputs added. 1 input removed. Training observations 600, was 300. Random seed none, was 42.");
  });

  it("says first whether the update stops or starts raising alarms", () => {
    const design = running();
    design.definition.settings = { ...design.definition.settings, training_window_size: 600 };
    const service = (was: boolean, now: boolean) => compareDesigns(running(), design, components, { was, now }).service;
    expect(service(false, true)).toEqual(["Runs in shadow", "Training observations 600, was 300"]);
    expect(service(true, false)).toEqual(["Goes live", "Training observations 600, was 300"]);
    // A service that stays as it is says nothing about it.
    expect(service(true, true)).toEqual(["Training observations 600, was 300"]);
    expect(comparisonSummary(compareDesigns(running(), running(), components, { was: true, now: false }))).toBe("Goes live.");
  });

  it("puts the change on the card of its step", () => {
    const design = setNodeParams(running(), "scale", { factor: 5 });
    const { nodes } = presentGraph(design, components, undefined, [], changed(design).steps);
    expect(nodes.find((item) => item.id === "scale")!.data.change).toEqual({ kind: "changed", detail: "Factor 5, was 3." });
    expect(nodes.find((item) => item.id === "smooth")!.data.change).toBeUndefined();
  });
});
