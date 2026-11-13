import { describe, expect, it } from "vitest";
import { normalizeCatalog, normalizeDefinition, normalizeView } from "@/features/pipelines/contracts";
import {
  changeCalibration,
  changeDetector,
  changeNotice,
  coverage,
  detectorLearning,
  fitPolicy,
  fittingPolicy,
  learningBlocker,
  learningLabel,
  learningSummary,
} from "@/features/pipelines/learning";
import { addDetector, connectionIssue, insertBlocker } from "@/features/pipelines/model";
import type * as Wire from "@/types/pipelines.generated";
import { groupOf } from "./support/fixtures/pipelines";

const component = (id: string, kind: Wire.PipelineComponent["kind"], learning: Wire.PipelineComponent["learning"],
  fields: Wire.ComponentField[] = [], facts: Partial<Wire.PipelineComponent> = {}): Wire.PipelineComponent => ({
  id, kind, group: groupOf(kind), label: id, description: "", learning, fields,
  input_type: kind === "source" ? null : kind === "calibration" ? "scores" : kind === "policy" ? "p_values" : "features",
  output_type: kind === "detector" ? "scores" : kind === "calibration" ? "p_values" : kind === "policy" ? "decisions" : "features",
  ...facts,
});
const alpha: Wire.ComponentField = { name: "alpha", label: "Alarm rate", type: "number", default: 0.01, has_default: true };
const fusion: Wire.ComponentField = { name: "fusion", label: "Combine", type: "enum", default: "max", has_default: true };
const catalog = normalizeCatalog({
  catalog_id: "learning", authoring_enabled: true,
  components: [
    component("source.aligned", "source", "none"),
    component("prepare.smooth", "transform", "none"),
    // The catalog names the step that learns the other way.
    component("static.standard_scaler", "transform", "batch", [
      { name: "with_mean", label: "Center", type: "boolean", default: true, has_default: true },
      { name: "with_std", label: "Scale", type: "boolean", default: true, has_default: true },
    ], { group: "normalize", counterpart: "adaptive.standard_scaler" }),
    component("adaptive.standard_scaler", "transform", "online", [
      { name: "with_std", label: "Scale", type: "boolean", default: true, has_default: true },
    ], { group: "normalize", counterpart: "static.standard_scaler" }),
    component("adaptive.only", "transform", "online"),
    component("detector:pyod_iforest", "detector", "batch", [
      { name: "n_estimators", label: "Trees", type: "integer", default: 100, has_default: true },
    ]),
    component("detector:aberrant_x_stream", "detector", "online"),
    component("forecast.timestral", "detector", "pretrained"),
    component("calibrate.fixed_split", "calibration", "none", [fusion],
      { label: "Fixed split", family: "conformal", coverage: "exchangeable" }),
    component("calibrate.aci", "calibration", "none", [alpha, fusion,
      { name: "gamma", label: "Step size", type: "number", default: 0.01, has_default: true }],
    { label: "ACI", family: "conformal", coverage: "long_run", reference: "Gibbs & Candes, NeurIPS 2021" }),
    component("calibrate.bocpd", "calibration", "none", [alpha, fusion],
      { label: "BOCPD", family: "bayesian", coverage: "none" }),
    component("policy.martingale", "policy", "none", [], { label: "Conformal alarm policy" }),
    component("policy.quantile", "policy", "none", [], { label: "Calibrated score threshold" }),
    component("policy.exceedance", "policy", "none", [], { label: "Exceedance rule" }),
  ],
  templates: [],
});
const components = catalog.components;
const find = (id: string) => components.find((item) => item.id === id)!;

/** input → scale → extra → model → calibrate → alarm, learning continuously. */
const continuous = () => normalizeDefinition({
  schema_version: 2,
  input_slots: [{ id: "value", label: "Value" }],
  nodes: [
    { id: "input", kind: "source", component: "source.aligned" },
    { id: "scale", kind: "transform", component: "adaptive.standard_scaler", params: { with_std: false } },
    { id: "extra", kind: "transform", component: "adaptive.only" },
    { id: "model", kind: "detector", component: "detector:aberrant_x_stream" },
    { id: "calibrate", kind: "calibration", component: "calibrate.fixed_split" },
    { id: "alarm", kind: "policy", component: "policy.quantile" },
  ],
  edges: [
    { source: "input", target: "scale" },
    { source: "scale", target: "extra" },
    { source: "extra", target: "model" },
    { source: "model", target: "calibrate" },
    { source: "calibrate", target: "alarm" },
  ],
});
const nodes = (definition: ReturnType<typeof continuous>) =>
  Object.fromEntries(definition.nodes.map((node) => [node.id, node]));

describe("a design without a strategy", () => {
  it("drops a strategy written with an older design", () => {
    const read = normalizeDefinition({ strategy: "static_baseline", nodes: [] });
    expect("strategy" in read).toBe(false);
    expect(read.schema_version).toBe(2);
  });

  it("says how its detectors learn", () => {
    expect(detectorLearning(continuous(), components)).toEqual(["online"]);
    expect(learningSummary(continuous(), components)).toBe("Learns continuously");
    expect(learningLabel(find("detector:pyod_iforest"))).toBe("Fitted once");
    expect(learningLabel(find("forecast.timestral"))).toBe("Pretrained");
    expect(learningLabel(find("prepare.smooth"))).toBeUndefined();
    const mixed = changeDetector(continuous(), "model", find("detector:pyod_iforest"), components).definition;
    const both = addDetector({ definition: continuous(), layout: { nodes: {} } }, "model")!.document.definition;
    expect(learningSummary(mixed, components)).toBe("Fitted once");
    expect(learningSummary(changeDetector(both, "model", find("detector:pyod_iforest"), components).definition, components))
      .toBe("Detectors learn differently");
    expect(learningSummary(normalizeDefinition({}), components)).toBe("No detector yet");
  });

  it("offers a learned step only where the detector learns the same way", () => {
    const definition = continuous();
    expect(learningBlocker(definition, "model", find("adaptive.standard_scaler"), components)).toBeUndefined();
    expect(learningBlocker(definition, "model", find("prepare.smooth"), components)).toBeUndefined();
    expect(learningBlocker(definition, "scale", find("static.standard_scaler"), components))
      .toBe("Fitted once, and the detector here learns continuously.");
    expect(insertBlocker(definition, { source: "extra", target: "model" }, find("static.standard_scaler"), components))
      .toBe("Fitted once, and the detector here learns continuously.");
    const fitted = changeDetector(definition, "model", find("detector:pyod_iforest"), components).definition;
    expect(learningBlocker(fitted, "model", find("adaptive.standard_scaler"), components))
      .toBe("Learns continuously, and the detector here is fitted once.");
    const pretrained = changeDetector(definition, "model", find("forecast.timestral"), components).definition;
    expect(learningBlocker(pretrained, "model", find("static.standard_scaler"), components))
      .toBe("The detector here is pretrained and reads only steps that do not learn.");
  });

  it("connects every detector to the calibration step, which takes several", () => {
    const added = addDetector({ definition: continuous(), layout: { nodes: {} } }, "model")!;
    const edges = added.document.definition.edges.filter((edge) => edge.target === "calibrate");
    expect(edges.map((edge) => [edge.source, edge.order])).toEqual([["model", 0], [added.id, 1]]);
    // The detection rule reads the calibration step alone.
    expect(connectionIssue(added.document.definition, added.id, "alarm", components))
      .toBe("Cannot connect Scores to Calibrated scores.");
  });
});

describe("changing how a detector learns", () => {
  it("moves the learned steps before it to their counterparts and fits the detection rule", () => {
    const before = continuous();
    const change = changeDetector(before, "model", find("detector:pyod_iforest"), components);
    const after = nodes(change.definition);
    // A learned step keeps the settings both versions share and takes defaults for the rest.
    expect(after.scale).toMatchObject({ component: "static.standard_scaler", params: { with_mean: true, with_std: false } });
    // A step without a counterpart stays; the check names it.
    expect(after.extra?.component).toBe("adaptive.only");
    expect(after.model).toMatchObject({ component: "detector:pyod_iforest", params: { n_estimators: 100 } });
    expect(after.alarm?.component).toBe("policy.martingale");
    expect(change.converted).toEqual(["scale"]);
    expect(change.definition.edges).toEqual(before.edges);
    expect(changeNotice(change, "batch")).toBe(
      "1 learned step moved to its fitted-once counterpart. The detection rule is now Conformal alarm policy. Undo reverses this.");
    expect(nodes(before).scale?.component).toBe("adaptive.standard_scaler");
  });

  it("leaves a learned step that another detector still reads as it is", () => {
    const both = addDetector({ definition: continuous(), layout: { nodes: {} } }, "model")!.document.definition;
    const change = changeDetector(both, "model", find("detector:pyod_iforest"), components);
    expect(change.converted).toEqual([]);
    expect(nodes(change.definition).scale?.component).toBe("adaptive.standard_scaler");
    // Detectors that learn differently meet at the fixed split and alarm on its threshold.
    expect(change.policy).toBeUndefined();
    expect(fittingPolicy(change.definition, components)).toBe("policy.quantile");
  });

  it("says nothing when only the model changed", () => {
    const change = changeDetector(continuous(), "model", find("detector:aberrant_x_stream"), components);
    expect(changeNotice(change, "online")).toBe("");
  });
});

describe("changing the calibration method", () => {
  it("keeps the alarm rate and how detectors combine, and moves to the exceedance rule", () => {
    const definition = continuous();
    definition.nodes.find((node) => node.id === "calibrate")!.params = { fusion: "mean" };
    const adapting = changeCalibration(definition, "calibrate", find("calibrate.aci"), components);
    expect(nodes(adapting.definition).calibrate).toMatchObject({
      component: "calibrate.aci", params: { alpha: 0.01, fusion: "mean", gamma: 0.01 },
    });
    expect(adapting.policy?.id).toBe("policy.exceedance");
    const tuned = adapting.definition;
    tuned.nodes.find((node) => node.id === "calibrate")!.params.alpha = 0.05;
    const bayesian = changeCalibration(tuned, "calibrate", find("calibrate.bocpd"), components);
    expect(nodes(bayesian.definition).calibrate?.params).toEqual({ alpha: 0.05, fusion: "mean" });
    expect(bayesian.policy).toBeUndefined();
    // Back at the fixed split, the rule follows the detectors again.
    const fixed = changeCalibration(bayesian.definition, "calibrate", find("calibrate.fixed_split"), components);
    expect(fixed.policy?.id).toBe("policy.quantile");
    expect(nodes(fixed.definition).calibrate?.params).toEqual({ fusion: "mean" });
  });

  it("names what each method promises", () => {
    expect(coverage(find("calibrate.fixed_split"))?.label).toBe("Exact while data stays alike");
    expect(coverage(find("calibrate.aci"))?.label).toBe("Long-run alarm rate");
    expect(coverage(find("calibrate.bocpd"))?.label).toBe("No guarantee");
    expect(coverage(find("policy.quantile"))).toBeUndefined();
  });

  it("leaves a rule that already fits", () => {
    const definition = continuous();
    expect(fitPolicy(definition, components).definition).toBe(definition);
  });
});

describe("a design arranged before calibration had a card", () => {
  it("puts the card at the detection rule's place and moves what follows one column over", () => {
    const view = normalizeView({
      id: "line", name: "Line", description: "", archived: false, version: 1, is_template: true,
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      draft: continuous(),
      layout: { nodes: {
        input: { x: 0, y: 100 }, scale: { x: 288, y: 100 }, extra: { x: 576, y: 100 }, model: { x: 864, y: 100 },
        alarm: { x: 1152, y: 100 }, note: { x: 1152, y: 300 },
      } },
      revisions: [],
    } as unknown as Wire.PipelineView);
    expect(view.layout.nodes).toEqual({
      input: { x: 0, y: 100 }, scale: { x: 288, y: 100 }, extra: { x: 576, y: 100 }, model: { x: 864, y: 100 },
      calibrate: { x: 1152, y: 100 }, alarm: { x: 1440, y: 100 }, note: { x: 1440, y: 300 },
    });
    // A layout that already places the card stays as it is.
    expect(normalizeView({ ...view, layout: view.layout } as unknown as Wire.PipelineView).layout).toEqual(view.layout);
  });
});
