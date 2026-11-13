import { describe, expect, it } from "vitest";
import { normalizeDefinition } from "@/features/pipelines/contracts";
import {
  observationSeconds,
  roughDuration,
  startupEstimate,
  startupPhases,
  startupSentence,
  startupSummary,
} from "@/features/pipelines/startup";

const definition = () => normalizeDefinition({
  input_slots: [{ id: "value", label: "Value" }],
  settings: { training_window_size: 1200, calibration_window_size: 360 },
});

describe("start-up estimate", () => {
  it("names the learning phase after how the detectors learn", () => {
    expect(startupPhases(definition()).map((phase) => [phase.label, phase.observations]))
      .toEqual([["Detector learning", 1200], ["Calibration", 360]]);
    // Detectors that are all fitted once are trained.
    expect(startupPhases(definition(), 0, "fitted")[0]?.label).toBe("Training");
    // Detectors that follow a rule learn nothing, so calibration is the whole start.
    expect(startupPhases(definition(), 0, "none").map((phase) => [phase.label, phase.observations]))
      .toEqual([["Calibration", 360]]);
    expect(startupSentence(startupEstimate(definition(), [], 79, "none")))
      .toBe("The first alarm can come after at least 439 observations: 79 to prepare and 360 to calibrate.");
  });

  it("is paced by the most frequent reading, and unknown while any reading has no interval", () => {
    expect(observationSeconds([1, 2.5, 0.2])).toBe(0.2);
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
    const timed = startupEstimate(definition(), [1, 2]);
    expect(startupSummary(timed)).toBe("≈ 26 min");
    expect(startupSentence(timed)).toBe("The first alarm can come after at least 1,560 observations: "
      + "1,200 to learn and 360 to calibrate. At one observation every 1 s, that is about 26 min.");
    const untimed = startupEstimate(definition(), [1, undefined], 0, "fitted");
    expect(startupSummary(untimed)).toBe("1,560 observations");
    expect(startupSentence(untimed)).toBe("The first alarm can come after at least 1,560 observations: "
      + "1,200 to train and 360 to calibrate.");
  });

  it("counts the observations Prepare steps need first, as the last check reported them", () => {
    const startup = startupEstimate(definition(), [1], 79);
    expect(startup.phases.map((phase) => [phase.label, phase.observations]))
      .toEqual([["Preparing", 79], ["Detector learning", 1200], ["Calibration", 360]]);
    expect(startupSentence(startup)).toBe("The first alarm can come after at least 1,639 observations: "
      + "79 to prepare, 1,200 to learn and 360 to calibrate. At one observation every 1 s, that is about 27 min.");
    expect(startupPhases(definition(), 0)).toHaveLength(2);
  });

  it("is a lower bound when a Gate can hold observations back", () => {
    const gated = { ...definition(), nodes: [
      { id: "gate", kind: "transform" as const, component: "prepare.gate", params: { condition: "value > 1" } },
    ] };
    const timed = startupEstimate(gated, [1], 10);
    expect(timed.gated).toBe(true);
    expect(startupSummary(timed)).toBe("≥ 26 min");
    expect(startupSentence(timed)).toBe("The first alarm can come after at least 1,570 observations: "
      + "10 to prepare, 1,200 to learn and 360 to calibrate. At one observation every 1 s, that is about 26 min. "
      + "A Gate holds back the observations its condition rejects, and they do not count, so it can take longer.");
    expect(startupSummary(startupEstimate(gated, [undefined]))).toBe("≥ 1,560 observations");
    expect(startupEstimate(definition(), [1]).gated).toBe(false);
  });
});
