import { describe, expect, it } from "vitest";
import { stepMenu } from "@/features/pipelines/contextMenu";
import { normalizeDefinition, type PipelineComponent } from "@/features/pipelines/contracts";
import { familyLabel, STEP_FAMILIES, stepFamily } from "@/features/pipelines/steps";
import { connectionIssue } from "@/features/pipelines/model";
import { dataKinds, takes } from "@/features/pipelines/semantics";

/** As the catalog lists them: a detector whose output is forecasts is filed as a forecaster. */
const detector = (id: string, label: string, output_type = "forecasts") => ({
  id, kind: "detector", group: output_type === "forecasts" ? "forecaster" : "detector", label,
  description: "Forecast the value of one cycle ago, and score the miss.",
  fields: [], input_type: "features", output_type,
}) as PipelineComponent;

const holtWinters = detector("detector:aberrant_holt_winters_forecaster", "Holt-Winters forecaster");
const seasonalNaive = detector("detector:aberrant_seasonal_naive_forecaster", "Seasonal naive forecaster");
const timestral = detector("forecast.timestral", "Timestral forecaster");
const knn = detector("detector:aberrant_knn", "k-nearest neighbors", "scores");
const calibration = { id: "calibrate.aci", kind: "calibration", group: "calibration", label: "ACI", description: "", fields: [],
  input_type: "scores", output_type: "p_values" } as PipelineComponent;
const policy = { id: "policy.exceedance", kind: "policy", group: "policy", label: "Exceedance rule", description: "", fields: [],
  input_type: "p_values", output_type: "decisions" } as PipelineComponent;

describe("Forecaster steps in the composer", () => {
  it("have a family of their own, listed before the other detectors", () => {
    const ids = STEP_FAMILIES.map((family) => family.id);
    expect(ids.indexOf("forecaster")).toBe(ids.indexOf("detector") - 1);
    expect(familyLabel("forecaster")).toBe("Forecaster");
    const step = { kind: "detector" } as const;
    expect(stepFamily(step, holtWinters)).toBe("forecaster");
    // A pretrained forecaster is one too, whichever service provides it.
    expect(stepFamily(step, timestral)).toBe("forecaster");
    expect(stepFamily(step, knn)).toBe("detector");
    // A detector the catalog no longer lists stays a detector.
    expect(stepFamily(step, undefined)).toBe("detector");
  });

  it("hand their forecasts to the calibration step and to nothing else", () => {
    expect(dataKinds.forecasts.label).toBe("Forecasts");
    expect(takes(calibration, "forecasts")).toBe(true);
    expect(takes(calibration, "scores")).toBe(true);
    expect(takes(policy, "forecasts")).toBe(false);
    const definition = normalizeDefinition({
      nodes: [
        { id: "forecaster", kind: "detector", component: holtWinters.id },
        { id: "calibrate", kind: "calibration", component: calibration.id },
        { id: "policy", kind: "policy", component: policy.id },
      ],
      edges: [],
    });
    const components = [holtWinters, calibration, policy];
    expect(connectionIssue(definition, "forecaster", "calibrate", components)).toBeUndefined();
    expect(connectionIssue(definition, "forecaster", "policy", components))
      .toBe("Cannot connect Forecasts to Calibrated scores.");
  });

  it("open from the add-step menu under Forecaster and are found by that word", () => {
    const steps = [knn, holtWinters, seasonalNaive, timestral];
    const menu = stepMenu("Add a step", steps, () => undefined, "Nothing fits.");
    expect(menu.items.map((item) => [item.label, item.detail])).toEqual([["Forecaster", "3"], ["Detector", "1"]]);
    expect(menu.search?.results("forecaster").map((item) => item.key))
      .toEqual([holtWinters.id, seasonalNaive.id, timestral.id]);
  });
});
