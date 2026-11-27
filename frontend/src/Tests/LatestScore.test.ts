// @vitest-environment node
import { describe, expect, it } from "vitest";
import { latestScoreText } from "@/features/charts/latest-score";
import type { DetectionObservation, SecondaryChartSeries } from "@/features/charts/telemetry-detectors";

const observation = (value: number | null, threshold: number | null, overrides: Partial<DetectionObservation> = {}): DetectionObservation => ({
  sequenceNumber: 1, timeMs: 0, value, threshold, alarmActive: false, alarmFired: false, logValue: null, isInfinite: false, ...overrides,
});
const series = (name: string, latest: DetectionObservation, relative?: boolean) =>
  ({ name, relative, latestObservation: latest }) as Pick<SecondaryChartSeries, "name" | "relative" | "latestObservation">;

describe("latestScoreText", () => {
  it("names a score drawn against its threshold as a share of it", () => {
    expect(latestScoreText(series("Joint anomaly score", observation(0.4064, 0.2983), true)))
      .toEqual({ headline: "Joint anomaly score: now 1.4× threshold", detail: "Score 0.4064, threshold 0.2983" });
  });

  it("keeps the score's own name and value when it is not drawn against its threshold", () => {
    expect(latestScoreText(series("Restarted e-process", observation(0.008615, 100))))
      .toEqual({ headline: "Restarted e-process: 0.008615", detail: "Score threshold: 100" });
  });

  it("says what is missing", () => {
    expect(latestScoreText(series("Anomaly score", observation(null, null))))
      .toEqual({ headline: "Anomaly score: unavailable", detail: "Score threshold: unavailable" });
    expect(latestScoreText(series("Anomaly score", observation(null, 2, { isInfinite: true }), true)))
      .toEqual({ headline: "Anomaly score: ∞", detail: "Score threshold: 2" });
  });
});
