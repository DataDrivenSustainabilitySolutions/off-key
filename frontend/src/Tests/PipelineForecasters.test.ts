import { describe, expect, it } from "vitest";
import { stepMenu } from "@/features/pipelines/contextMenu";
import type { PipelineComponent } from "@/features/pipelines/contracts";
import { familyLabel, STEP_FAMILIES, stepDescription, stepFamily } from "@/features/pipelines/steps";

const detector = (id: string, label: string) => ({
  id, kind: "detector", label, description: "Scores a feature by how far it misses its forecast.",
  strategies: ["adaptive_stream"], fields: [], input_type: "features", output_type: "scores",
}) as PipelineComponent;

const holtWinters = detector("detector:aberrant_holt_winters_forecaster", "Aberrant HoltWinters forecaster");
const seasonalNaive = detector("detector:aberrant_seasonal_naive_forecaster", "Aberrant SeasonalNaive forecaster");
const knn = detector("detector:aberrant_knn", "Aberrant KNN");

describe("Forecaster steps in the composer", () => {
  it("have a family of their own, listed before the other detectors", () => {
    const ids = STEP_FAMILIES.map((family) => family.id);
    expect(ids.indexOf("forecaster")).toBe(ids.indexOf("detector") - 1);
    expect(familyLabel("forecaster")).toBe("Forecaster");
    expect(stepFamily("detector", holtWinters.id)).toBe("forecaster");
    expect(stepFamily("detector", seasonalNaive.id)).toBe("forecaster");
    // A pretrained forecaster is one too, whichever service provides it.
    expect(stepFamily("detector", "forecast.timestral")).toBe("forecaster");
    expect(stepFamily("detector", knn.id)).toBe("detector");
    // The seasonal residual detector keeps its place: it has no lead to choose.
    expect(stepFamily("detector", "detector:aberrant_seasonal_residual_detector")).toBe("detector");
  });

  it("say what they expect in one line each", () => {
    expect(stepDescription(holtWinters)).toMatch(/level, a trend and a repeating cycle/);
    expect(stepDescription(seasonalNaive)).toMatch(/one cycle ago/);
  });

  it("open from the add-step menu under Forecaster and are found by that word", () => {
    const menu = stepMenu("Add a step", [knn, holtWinters, seasonalNaive], () => undefined, "Nothing fits.");
    expect(menu.items.map((item) => [item.label, item.detail])).toEqual([["Forecaster", "2"], ["Detector", "1"]]);
    expect(menu.search?.results("forecaster").map((item) => item.key)).toEqual([holtWinters.id, seasonalNaive.id]);
  });
});
