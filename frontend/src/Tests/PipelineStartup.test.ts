import { describe, expect, it } from "vitest";
import { normalizeCatalog, normalizeDefinition, normalizeLayout } from "@/features/pipelines/contracts";
import {
  observationSeconds,
  roughDuration,
  startupEstimate,
  startupPhases,
  startupSentence,
  startupSummary,
} from "@/features/pipelines/startup";
import { convertStrategy } from "@/features/pipelines/strategy";
import type * as Wire from "@/types/pipelines.generated";

const definition = (strategy: "static_baseline" | "adaptive_stream") => normalizeDefinition({
  strategy,
  input_slots: [{ id: "value", label: "Value" }],
  settings: { training_window_size: 1200, calibration_window_size: 360 },
});

describe("start-up estimate", () => {
  it("names the phases after the strategy", () => {
    expect(startupPhases(definition("adaptive_stream")).map((phase) => [phase.label, phase.observations]))
      .toEqual([["Detector learning", 1200], ["Calibration", 360]]);
    expect(startupPhases(definition("static_baseline"))[0]?.label).toBe("Training");
  });

  it("is paced by the slowest reading, and unknown while any reading has no interval", () => {
    expect(observationSeconds([1, 2.5, 0.2])).toBe(2.5);
    expect(observationSeconds([])).toBeUndefined();
    expect(observationSeconds([1, null])).toBeUndefined();
    expect(observationSeconds([1, 0])).toBeUndefined();
    expect(observationSeconds([Number.NaN])).toBeUndefined();
  });

  it("rounds durations to what a person would say", () => {
    expect([0.5, 45, 1560, 7800, 7200, 108_000, 259_200].map(roughDuration))
      .toEqual(["0.5 s", "45 s", "26 min", "2 h 10 min", "2 h", "30 h", "3 days"]);
  });

  it("summarizes in time when it can, otherwise in observations", () => {
    const timed = startupEstimate(definition("adaptive_stream"), [1, 0.5]);
    expect(startupSummary(timed)).toBe("≈ 26 min");
    expect(startupSentence(timed)).toBe("The first alarm can come after at least 1,560 observations: "
      + "1,200 to learn and 360 to calibrate. At one observation every 1 s, that is about 26 min.");
    const untimed = startupEstimate(definition("static_baseline"), [1, undefined]);
    expect(startupSummary(untimed)).toBe("1,560 observations");
    expect(startupSentence(untimed)).toBe("The first alarm can come after at least 1,560 observations: "
      + "1,200 to train and 360 to calibrate.");
  });

  it("counts the observations Prepare steps need first, as the last check reported them", () => {
    const startup = startupEstimate(definition("adaptive_stream"), [1], 79);
    expect(startup.phases.map((phase) => [phase.label, phase.observations]))
      .toEqual([["Preparing", 79], ["Detector learning", 1200], ["Calibration", 360]]);
    expect(startupSentence(startup)).toBe("The first alarm can come after at least 1,639 observations: "
      + "79 to prepare, 1,200 to learn and 360 to calibrate. At one observation every 1 s, that is about 27 min.");
    expect(startupPhases(definition("adaptive_stream"), 0)).toHaveLength(2);
  });

  it("is a lower bound when a Gate can hold observations back", () => {
    const gated = { ...definition("adaptive_stream"), nodes: [
      { id: "gate", kind: "transform" as const, component: "prepare.gate", params: { condition: "value > 1" } },
    ] };
    const timed = startupEstimate(gated, [1], 10);
    expect(timed.gated).toBe(true);
    expect(startupSummary(timed)).toBe("≥ 26 min");
    expect(startupSentence(timed)).toBe("The first alarm can come after at least 1,570 observations: "
      + "10 to prepare, 1,200 to learn and 360 to calibrate. At one observation every 1 s, that is about 26 min. "
      + "A Gate holds back the observations its condition rejects, and they do not count, so it can take longer.");
    expect(startupSummary(startupEstimate(gated, [undefined]))).toBe("≥ 1,560 observations");
    expect(startupEstimate(definition("adaptive_stream"), [1]).gated).toBe(false);
  });
});

const component = (id: string, kind: Wire.PipelineComponent["kind"], strategies: Wire.PipelineComponent["strategies"],
  fields: Wire.ComponentField[] = []): Wire.PipelineComponent => ({
  id, kind, label: id, description: "", strategies, fields,
  input_type: kind === "source" ? null : kind === "policy" ? "scores" : "features",
  output_type: kind === "detector" ? "scores" : kind === "policy" ? "decisions" : "features",
});
const both: Wire.PipelineComponent["strategies"] = ["static_baseline", "adaptive_stream"];
const catalog = normalizeCatalog({
  catalog_id: "strategy", authoring_enabled: true,
  components: [
    component("source.aligned", "source", both),
    component("static.standard_scaler", "transform", ["static_baseline"], [
      { name: "with_mean", label: "Center", type: "boolean", default: true, has_default: true },
      { name: "with_std", label: "Scale", type: "boolean", default: true, has_default: true },
    ]),
    component("adaptive.standard_scaler", "transform", ["adaptive_stream"], [
      { name: "with_std", label: "Scale", type: "boolean", default: true, has_default: true },
    ]),
    component("adaptive.only", "transform", ["adaptive_stream"]),
    component("detector:pyod_iforest", "detector", ["static_baseline"], [
      { name: "n_estimators", label: "Trees", type: "integer", default: 100, has_default: true },
    ]),
    component("detector:aberrant_online_isolation_forest", "detector", ["adaptive_stream"], [
      { name: "window_size", label: "Window", type: "integer", default: 2048, has_default: true },
    ]),
    component("detector:aberrant_x_stream", "detector", ["adaptive_stream"]),
    component("policy.martingale", "policy", ["static_baseline"]),
    component("policy.quantile", "policy", ["adaptive_stream"]),
  ],
  templates: [{
    id: "static_baseline", name: "Static baseline", layout: normalizeLayout(),
    definition: normalizeDefinition({ strategy: "static_baseline", nodes: [
      { id: "detector", kind: "detector", component: "detector:pyod_iforest" },
      { id: "policy", kind: "policy", component: "policy.martingale" },
    ] }),
  }, {
    id: "adaptive_stream", name: "Adaptive stream", layout: normalizeLayout(),
    definition: normalizeDefinition({ strategy: "adaptive_stream", nodes: [
      { id: "detector", kind: "detector", component: "detector:aberrant_online_isolation_forest" },
      { id: "policy", kind: "policy", component: "policy.quantile" },
    ] }),
  }],
});
const adaptive = () => ({
  definition: normalizeDefinition({
    strategy: "adaptive_stream",
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "scale", kind: "transform", component: "adaptive.standard_scaler", params: { with_std: false } },
      { id: "extra", kind: "transform", component: "adaptive.only" },
      { id: "model", kind: "detector", component: "detector:aberrant_x_stream" },
      { id: "alarm", kind: "policy", component: "policy.quantile" },
    ],
    edges: [
      { source: "input", target: "scale" },
      { source: "scale", target: "extra" },
      { source: "extra", target: "model" },
      { source: "model", target: "alarm" },
    ],
  }),
  layout: normalizeLayout({ nodes: { scale: { x: 10, y: 20, label: "Power scaling" } } }),
});

describe("strategy switch", () => {
  it("moves learned steps to their counterparts and keeps the graph's shape", () => {
    const before = adaptive();
    const change = convertStrategy(before, "static_baseline", catalog);
    const nodes = Object.fromEntries(change.document.definition.nodes.map((node) => [node.id, node]));
    expect(change.document.definition.strategy).toBe("static_baseline");
    expect(change.converted).toEqual(["scale", "model", "alarm"]);
    expect(change.unconverted).toEqual(["extra"]);
    // A learned step keeps the settings both versions share and takes defaults for the rest.
    expect(nodes.scale).toMatchObject({ component: "static.standard_scaler", params: { with_mean: true, with_std: false } });
    // A detector without a pair becomes the strategy's template detector, with its defaults.
    expect(nodes.model).toMatchObject({ component: "detector:pyod_iforest", params: { n_estimators: 100 } });
    expect(nodes.alarm?.component).toBe("policy.martingale");
    expect(nodes.extra?.component).toBe("adaptive.only");
    expect(change.document.definition.edges).toEqual(before.definition.edges);
    expect(change.document.layout).toEqual(before.layout);
    expect(before.definition.strategy).toBe("adaptive_stream");
  });

  it("uses a detector's own counterpart when there is one", () => {
    const before = convertStrategy(adaptive(), "static_baseline", catalog).document;
    const back = convertStrategy(before, "adaptive_stream", catalog);
    const model = back.document.definition.nodes.find((node) => node.id === "model");
    expect(model).toMatchObject({ component: "detector:aberrant_online_isolation_forest", params: { window_size: 2048 } });
    expect(back.unconverted).toEqual([]);
  });
});
