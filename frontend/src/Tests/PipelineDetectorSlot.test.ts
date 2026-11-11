import { describe, expect, it, vi } from "vitest";
import { normalizeCatalog, normalizeDefinition, normalizeLayout } from "@/features/pipelines/contracts";
import {
  detectorMenu, detectorSlot, fillDetectorSlot, starterTemplate, suggestedDetector, withoutDetector,
} from "@/features/pipelines/detectorSlot";
import type { GraphDocument } from "@/features/pipelines/model";
import { NODE_SIZE } from "@/features/pipelines/semantics";
import type * as Wire from "@/types/pipelines.generated";

const component = (id: string, kind: Wire.PipelineComponent["kind"], learning: Wire.PipelineComponent["learning"],
  facts: Partial<Wire.PipelineComponent> = {}): Wire.PipelineComponent => ({
  id, kind, label: id, description: "Scores each observation.", learning, fields: [],
  input_type: kind === "source" ? null : kind === "calibration" ? "scores" : kind === "policy" ? "p_values"
    : kind === "output" ? "decisions" : "features",
  output_type: kind === "detector" ? "scores" : kind === "calibration" ? "p_values" : kind === "policy" ? "decisions"
    : kind === "output" ? "evidence" : "features",
  ...facts,
});

/** input → detector → calibrate → policy → output, one column apart. */
const flow = (detector: string): Wire.PipelineDefinition => ({
  schema_version: 2,
  input_slots: [{ id: "value", label: "Value" }],
  nodes: [
    { id: "input", kind: "source", component: "source.aligned" },
    { id: "detector", kind: "detector", component: detector },
    { id: "calibrate", kind: "calibration", component: "calibrate.fixed_split" },
    { id: "policy", kind: "policy", component: "policy.quantile" },
    { id: "output", kind: "output", component: "sink.evidence" },
  ],
  edges: [
    { source: "input", target: "detector" },
    { source: "detector", target: "calibrate" },
    { source: "calibrate", target: "policy" },
    { source: "policy", target: "output" },
  ],
});
const row = (ids: string[]) => ({ nodes: Object.fromEntries(ids.map((id, index) => [id, { x: index * 288, y: 100 }])) });
const catalog = normalizeCatalog({
  catalog_id: "slot", authoring_enabled: true,
  components: [
    component("source.aligned", "source", "none"),
    component("features.passthrough", "transform", "none", { label: "Pass through" }),
    component("adaptive.standard_scaler", "transform", "online", { label: "Online standard scaling" }),
    component("static.standard_scaler", "transform", "batch", { label: "Standard scaling" }),
    component("detector:pyod_iforest", "detector", "batch", { label: "Isolation forest" }),
    component("detector:aberrant_half_space", "detector", "online", { label: "Half-space trees" }),
    component("detector:aberrant_x_stream", "detector", "online", { label: "xStream" }),
    component("forecast.timestral", "detector", "pretrained", { label: "Timestral" }),
    component("calibrate.fixed_split", "calibration", "none"),
    component("policy.quantile", "policy", "none"),
    component("policy.martingale", "policy", "none"),
    component("sink.evidence", "output", "none"),
  ],
  templates: [
    { id: "static_baseline", name: "Static baseline", definition: flow("detector:pyod_iforest"),
      layout: row(["input", "detector", "calibrate", "policy", "output"]) },
    { id: "adaptive_stream", name: "Adaptive stream", definition: flow("detector:aberrant_x_stream"),
      layout: row(["input", "detector", "calibrate", "policy", "output"]) },
  ],
});
const components = catalog.components;
const find = (id: string) => components.find((item) => item.id === id)!;
const starter = (): GraphDocument => {
  const template = starterTemplate(catalog)!;
  return { definition: template.definition, layout: template.layout };
};
const withStep = (document: GraphDocument, node: Wire.PipelineNode, at: { x: number; y: number },
  edges: Array<[string, string]> = []): GraphDocument => ({
  definition: normalizeDefinition({
    ...document.definition,
    nodes: [...document.definition.nodes, node],
    edges: [...document.definition.edges, ...edges.map(([source, target]) => ({ source, target }))],
  }),
  layout: normalizeLayout({ ...document.layout, nodes: { ...document.layout.nodes, [node.id]: at } }),
});

describe("the flow a new service starts from", () => {
  it("is the one whose detector learns from the stream", () => {
    expect(starterTemplate(catalog)?.id).toBe("adaptive_stream");
    expect(suggestedDetector(catalog)?.id).toBe("detector:aberrant_x_stream");
  });

  it("falls back to the first flow when every detector is fitted once", () => {
    const fitted = { ...catalog, templates: catalog.templates.slice(0, 1) };
    expect(starterTemplate(fitted)?.id).toBe("static_baseline");
    expect(starterTemplate({ ...catalog, templates: [] })).toBeUndefined();
    expect(suggestedDetector({ ...catalog, templates: [] })).toBeUndefined();
  });

  it("leaves the detector out and keeps every other step where it was", () => {
    const open = withoutDetector(starter());
    expect(open.definition.nodes.map((node) => node.id)).toEqual(["input", "calibrate", "policy", "output"]);
    expect(open.definition.edges.map((edge) => [edge.source, edge.target])).toEqual([["calibrate", "policy"], ["policy", "output"]]);
    expect(open.layout.nodes.calibrate).toEqual({ x: 576, y: 100 });
  });
});

describe("detectorSlot", () => {
  it("is absent while the design has a detector", () => {
    expect(detectorSlot(starter(), components)).toBeUndefined();
  });

  it("sits where the detector was: after the input, before the calibration step", () => {
    expect(detectorSlot(withoutDetector(starter()), components))
      .toEqual({ position: { x: 288, y: 100 }, after: "input", before: "calibrate" });
  });

  it("continues from the last step the readings reach", () => {
    const scaled = withStep(withoutDetector(starter()),
      { id: "scale", kind: "transform", component: "adaptive.standard_scaler" }, { x: 288, y: 100 }, [["input", "scale"]]);
    const slot = detectorSlot(scaled, components)!;
    expect(slot.after).toBe("scale");
    expect(slot.before).toBe("calibrate");
    // The place before the calibration step is taken, so the slot moves clear of every card.
    for (const at of Object.values(scaled.layout.nodes))
      expect(Math.abs(at.x - slot.position.x) >= NODE_SIZE.width || Math.abs(at.y - slot.position.y) >= NODE_SIZE.height).toBe(true);
  });

  it("does not continue from a step that reads nothing yet", () => {
    const loose = withStep(withoutDetector(starter()),
      { id: "aside", kind: "transform", component: "features.passthrough" }, { x: 1600, y: 400 });
    expect(detectorSlot(loose, components)).toEqual({ position: { x: 288, y: 100 }, after: "input", before: "calibrate" });
  });

  it("connects only on the input side when the design has no calibration step", () => {
    const document = withoutDetector(starter());
    const bare: GraphDocument = { ...document, definition: { ...document.definition,
      nodes: document.definition.nodes.filter((node) => node.kind !== "calibration"),
      edges: [] } };
    expect(detectorSlot(bare, components)).toEqual(expect.objectContaining({ after: "input", before: undefined }));
  });
});

describe("fillDetectorSlot", () => {
  it("places the detector in the slot and connects both sides", () => {
    const filled = fillDetectorSlot(withoutDetector(starter()), find("detector:aberrant_half_space"), components)!;
    expect(filled.id).toBe("detector");
    expect(filled.notice).toBe("");
    // Steps stay listed in the order the flow reads.
    expect(filled.document.definition.nodes.map((node) => node.id)).toEqual(["input", "detector", "calibrate", "policy", "output"]);
    expect(filled.document.definition.nodes[1]).toEqual(expect.objectContaining({ kind: "detector", component: "detector:aberrant_half_space" }));
    expect(filled.document.definition.edges.map((edge) => [edge.source, edge.target])).toEqual(
      [["input", "detector"], ["detector", "calibrate"], ["calibrate", "policy"], ["policy", "output"]]);
    expect(filled.document.layout.nodes.detector).toEqual({ x: 288, y: 100 });
    expect(detectorSlot(filled.document, components)).toBeUndefined();
  });

  it("takes the learned steps before it along and says so", () => {
    const scaled = withStep(withoutDetector(starter()),
      { id: "scale", kind: "transform", component: "adaptive.standard_scaler" }, { x: 288, y: 300 }, [["input", "scale"]]);
    const filled = fillDetectorSlot(scaled, find("detector:pyod_iforest"), components)!;
    const scale = filled.document.definition.nodes.find((node) => node.id === "scale")!;
    expect(scale.component).toBe("static.standard_scaler");
    expect(filled.notice).not.toBe("");
    expect(filled.document.definition.edges.map((edge) => [edge.source, edge.target]))
      .toEqual(expect.arrayContaining([["scale", "detector"], ["detector", "calibrate"]]));
  });

  it("gives the detector a name no other step has", () => {
    const named = withStep(withoutDetector(starter()),
      { id: "detector", kind: "transform", component: "features.passthrough" }, { x: 288, y: 300 }, [["input", "detector"]]);
    expect(fillDetectorSlot(named, find("detector:aberrant_x_stream"), components)!.id).toBe("detector_2");
  });

  it("does nothing without a slot, for another kind of step or for a detector this deployment lacks", () => {
    const open = withoutDetector(starter());
    expect(fillDetectorSlot(starter(), find("detector:aberrant_x_stream"), components)).toBeUndefined();
    expect(fillDetectorSlot(open, find("features.passthrough"), components)).toBeUndefined();
    expect(fillDetectorSlot(open, { ...find("forecast.timestral"), unavailable: "No forecast service." }, components)).toBeUndefined();
  });
});

describe("detectorMenu", () => {
  it("offers the suggested detector first, then every detector by how it learns", () => {
    const pick = vi.fn();
    const menu = detectorMenu(components, find("detector:aberrant_x_stream"), pick);
    expect(menu.label).toBe("Choose a detector");
    expect(menu.items.map((item) => [item.key, item.label, item.detail])).toEqual([
      ["suggested:detector:aberrant_x_stream", "xStream", "Suggested"],
      ["online", "Learns continuously", "2"],
      ["batch", "Fitted once", "1"],
      ["pretrained", "Pretrained", "1"],
    ]);
    expect(menu.items[1]!.separated).toBe(true);
    expect(menu.items[1]!.submenu!.items.map((item) => item.label)).toEqual(["Half-space trees", "xStream"]);
    menu.items[0]!.run!();
    expect(pick).toHaveBeenCalledExactlyOnceWith(find("detector:aberrant_x_stream"));
  });

  it("finds detectors by name and by how they learn", () => {
    const menu = detectorMenu(components, undefined, vi.fn());
    expect(menu.items.map((item) => item.key)).toEqual(["online", "batch", "pretrained"]);
    expect(menu.search!.results("forest").map((item) => item.label)).toEqual(["Isolation forest"]);
    expect(menu.search!.results("learns continuously").map((item) => [item.label, item.detail]))
      .toEqual([["Half-space trees", "Learns continuously"], ["xStream", "Learns continuously"]]);
    expect(menu.search!.results("no such model")).toEqual([]);
  });

  it("keeps a detector this deployment cannot run in its group, blocked, and never suggests it", () => {
    const offered = components.map((item) => item.id === "forecast.timestral" ? { ...item, unavailable: "No forecast service." } : item);
    const menu = detectorMenu(offered, offered.find((item) => item.id === "forecast.timestral"), vi.fn());
    expect(menu.items.map((item) => item.key)).toEqual(["online", "batch", "pretrained"]);
    expect(menu.items[2]!.submenu!.items[0]).toEqual(expect.objectContaining({ label: "Timestral", blocked: "No forecast service." }));
  });
});
