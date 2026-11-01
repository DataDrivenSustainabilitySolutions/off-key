// @vitest-environment node
import { describe, expect, it } from "vitest";
import { normalizeDefinition, type PipelineComponent, type PipelineNode } from "@/features/pipelines/contracts";
import { nodeSummary } from "@/features/pipelines/summaries";

const definition = normalizeDefinition({
  strategy: "adaptive_stream",
  input_slots: [
    { id: "value", label: "DC voltage" },
    { id: "input_2", label: "DC current" },
    { id: "input_3", label: "" },
  ],
  nodes: [],
  edges: [
    { source: "a", target: "merge", order: 0 },
    { source: "b", target: "merge", order: 1 },
  ],
});
const node = (component: string, params: PipelineNode["params"] = {}): PipelineNode =>
  ({ id: "node", kind: "transform", component, params });
const summary = (component: string, params?: PipelineNode["params"], metadata?: PipelineComponent) =>
  nodeSummary(node(component, params), metadata, definition);

describe("card summaries", () => {
  it("names what the structural steps do with their features", () => {
    expect(summary("source.aligned")).toEqual({ text: "3 readings" });
    // Selections list reading labels, falling back to the key when a slot has none.
    expect(summary("features.select", { features: ["input_2", "input_3", "derived"] }))
      .toEqual({ chips: ["DC current", "input_3", "derived"] });
    expect(summary("features.select", { features: [] })).toEqual({ text: "No features chosen" });
    expect(summary("features.rename", { mapping: { value: "voltage", input_2: "current" } }))
      .toEqual({ text: "Renames 2 features" });
    expect(summary("features.rename", { mapping: {} })).toEqual({ text: "No names changed" });
    expect(nodeSummary({ ...node("features.merge"), id: "merge" }, undefined, definition))
      .toEqual({ text: "2 inputs, in order" });
  });

  it("summarizes the settings that shape the numbers", () => {
    expect(summary("adaptive.min_max_scaler", { feature_range: [-1, 1], clip: true }))
      .toEqual({ text: "Range -1 to 1 · clipped" });
    expect(summary("static.min_max_scaler")).toEqual({ text: "Range 0 to 1" });
    expect(summary("adaptive.standard_scaler", { with_std: false })).toEqual({ text: "Centering only" });
    expect(summary("adaptive.standard_scaler", { with_std: true })).toEqual({});
    expect(summary("static.pca", { n_components: 3 })).toEqual({ text: "3 components" });
    expect(summary("policy.quantile", { quantile: 1 })).toEqual({ text: "Above the calibration maximum" });
    expect(summary("policy.quantile", { quantile: 0.995 })).toEqual({ text: "Above calibration quantile 0.995" });
  });

  it("lists changed detector settings against the catalogue defaults", () => {
    const detector: PipelineComponent = {
      id: "detector:forest", kind: "detector", label: "Forest", description: "", strategies: ["adaptive_stream"],
      fields: [
        { name: "window_size", label: "Window Size", type: "integer", default: 2048 },
        { name: "metric", label: "Metric", type: "enum", default: "axisparallel" },
        { name: "subsample", label: "Subsample", type: "number", default: 1 },
        { name: "bounds", label: "Gamma Bounds", type: "number_pair", default: [0.001, 100] },
      ],
    };
    expect(summary("detector:forest", { window_size: 2048 }, detector)).toEqual({ text: undefined });
    expect(summary("detector:forest", { window_size: 500, metric: "oblique_split" }, detector))
      .toEqual({ text: "Window size 500 · Metric oblique split" });
    expect(summary("detector:forest", { window_size: 500, metric: "oblique_split", subsample: 0.25 }, detector))
      .toEqual({ text: "Window size 500 · Metric oblique split · 1 more setting" });
    expect(summary("detector:forest", { bounds: [0.01, 10] }, detector)).toEqual({ text: "Gamma bounds 0.01 to 10" });
    // An unknown component has no catalogue entry to compare against.
    expect(summary("detector:missing", { window_size: 1 })).toEqual({});
  });
});
