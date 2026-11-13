import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { normalizeCatalog, normalizeDefinition } from "@/features/pipelines/contracts";
import {
  changeCalibration,
  changeDetector,
  detectorLearning,
  fittingPolicy,
  hasFittedDetector,
  hasStreamingDetector,
  learningBlocker,
  learningLabel,
  learningSummary,
  learningWindow,
} from "@/features/pipelines/learning";
import { addDetector } from "@/features/pipelines/model";
import { PipelineDesignSettings } from "@/features/pipelines/PipelineDesignSettings";
import { startupEstimate } from "@/features/pipelines/startup";
import type * as Wire from "@/types/pipelines.generated";

const component = (id: string, kind: Wire.PipelineComponent["kind"], learning: Wire.PipelineComponent["learning"],
  label = id): Wire.PipelineComponent => ({
  id, kind, label, description: "", learning, fields: [],
  group: kind === "source" ? "input" : kind === "transform" ? "prepare" : kind === "merge" ? "route" : kind,
  input_type: kind === "source" ? null : kind === "calibration" ? "scores" : kind === "policy" ? "p_values" : "features",
  output_type: kind === "detector" ? "scores" : kind === "calibration" ? "p_values" : kind === "policy" ? "decisions" : "features",
});
const catalog = normalizeCatalog({
  catalog_id: "rule", authoring_enabled: true,
  components: [
    component("source.aligned", "source", "none"),
    component("prepare.formula", "transform", "none"),
    component("static.standard_scaler", "transform", "batch"),
    component("adaptive.standard_scaler", "transform", "online"),
    component("rule.score", "detector", "none", "Rule detector"),
    component("detector:pyod_iforest", "detector", "batch"),
    component("detector:aberrant_x_stream", "detector", "online"),
    component("calibrate.fixed_split", "calibration", "none"),
    component("calibrate.aci", "calibration", "none"),
    component("policy.martingale", "policy", "none", "Conformal alarm policy"),
    component("policy.quantile", "policy", "none", "Calibrated score threshold"),
    component("policy.exceedance", "policy", "none", "Exceedance rule"),
  ],
  templates: [],
});
const components = catalog.components;
const find = (id: string) => components.find((item) => item.id === id)!;

/** input → limit → rule → calibrate → alarm: a formula states the rule. */
const ruled = () => normalizeDefinition({
  schema_version: 2,
  input_slots: [{ id: "value", label: "Value" }],
  nodes: [
    { id: "input", kind: "source", component: "source.aligned" },
    { id: "limit", kind: "transform", component: "prepare.formula" },
    { id: "rule", kind: "detector", component: "rule.score" },
    { id: "calibrate", kind: "calibration", component: "calibrate.fixed_split" },
    { id: "alarm", kind: "policy", component: "policy.quantile" },
  ],
  edges: [
    { source: "input", target: "limit" },
    { source: "limit", target: "rule" },
    { source: "rule", target: "calibrate" },
    { source: "calibrate", target: "alarm" },
  ],
  settings: { training_window_size: 1200, calibration_window_size: 360 },
});
const policyOf = (definition: ReturnType<typeof ruled>) =>
  definition.nodes.find((node) => node.kind === "policy")?.component;

describe("a detector that follows a rule", () => {
  it("says that it learns nothing, where other detectors say how they learn", () => {
    expect(learningLabel(find("rule.score"))).toBe("No training");
    // A step that does not learn still says nothing.
    expect(learningLabel(find("prepare.formula"))).toBeUndefined();
    expect(detectorLearning(ruled(), components)).toEqual(["none"]);
    expect(learningSummary(ruled(), components)).toBe("No training");
    const beside = addDetector({ definition: ruled(), layout: { nodes: {} } }, "rule")!;
    const mixed = changeDetector(beside.document.definition, beside.id, find("detector:aberrant_x_stream"), components).definition;
    expect(learningSummary(mixed, components)).toBe("Detectors learn differently");
  });

  it("scores every observation as it arrives, without a learning window", () => {
    expect(hasStreamingDetector(ruled(), components)).toBe(true);
    expect(hasFittedDetector(ruled(), components)).toBe(false);
    expect(learningWindow(ruled(), components)).toBe("none");
    expect(startupEstimate(ruled(), [1], 0, learningWindow(ruled(), components)).observations).toBe(360);
    // Beside a detector that learns, the design keeps its learning window.
    const beside = addDetector({ definition: ruled(), layout: { nodes: {} } }, "rule")!;
    const learns = changeDetector(beside.document.definition, beside.id, find("detector:aberrant_x_stream"), components).definition;
    expect(learningWindow(learns, components)).toBe("continuous");
    const fitted = changeDetector(ruled(), "rule", find("detector:pyod_iforest"), components).definition;
    expect(learningWindow(fitted, components)).toBe("fitted");
    expect(learningWindow(normalizeDefinition({}), components)).toBe("fitted");
  });

  it("reads only steps that do not learn", () => {
    expect(learningBlocker(ruled(), "rule", find("prepare.formula"), components)).toBeUndefined();
    for (const step of ["adaptive.standard_scaler", "static.standard_scaler"])
      expect(learningBlocker(ruled(), "limit", find(step), components))
        .toBe("The detector here follows a rule and reads only steps that do not learn.");
  });

  it("alarms on its score: a threshold under the fixed split, a boundary otherwise", () => {
    expect(fittingPolicy(ruled(), components)).toBe("policy.quantile");
    const adapting = changeCalibration(ruled(), "calibrate", find("calibrate.aci"), components);
    expect(policyOf(adapting.definition)).toBe("policy.exceedance");
    // A design that alarmed on p-values moves to the score threshold with the detector.
    const fitted = changeDetector(ruled(), "rule", find("detector:pyod_iforest"), components);
    expect(policyOf(fitted.definition)).toBe("policy.martingale");
    const back = changeDetector(fitted.definition, "rule", find("rule.score"), components);
    expect(policyOf(back.definition)).toBe("policy.quantile");
    expect(back.policy?.label).toBe("Calibrated score threshold");
  });

  it("leaves the learning window out of the design's settings", () => {
    const view = render(<PipelineDesignSettings document={{ definition: ruled(), layout: { nodes: {} } }} catalog={catalog}
      readOnly={false} onChange={() => undefined} />);
    expect(screen.getByText(/follow a rule and learn nothing, so calibration starts with the first observation/)).toBeTruthy();
    expect(screen.getAllByRole("spinbutton").map((item) => item.getAttribute("aria-label") ?? item.closest("label")?.textContent))
      .toEqual(["Calibration observations", "Default random seed"]);
    expect(screen.queryByText(/Upstream steps initialize first/)).toBeNull();
    const learns = changeDetector(ruled(), "rule", find("detector:aberrant_x_stream"), components).definition;
    view.rerender(<PipelineDesignSettings document={{ definition: learns, layout: { nodes: {} } }} catalog={catalog}
      readOnly={false} onChange={() => undefined} />);
    expect(screen.getByRole("spinbutton", { name: "Detector learning updates before calibration" })).toBeTruthy();
    expect(screen.getByText(/Upstream steps initialize first/)).toBeTruthy();
  });
});
