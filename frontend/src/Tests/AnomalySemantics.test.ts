import { describe, expect, it } from "vitest";

import {
  formatAnomalyZScore,
  getAnomalyZScoreClassName,
} from "../lib/anomaly-semantics";

describe("anomaly semantics formatting", () => {
  it("formats anomaly value as z-score text", () => {
    expect(formatAnomalyZScore(4.237)).toBe("4.24");
  });

  it("uses red severity styling for high z-scores", () => {
    expect(getAnomalyZScoreClassName(6.1)).toContain("bg-red-100");
  });

  it("uses orange severity styling for medium z-scores", () => {
    expect(getAnomalyZScoreClassName(4.2)).toContain("bg-orange-100");
  });

  it("uses yellow severity styling for lower z-scores", () => {
    expect(getAnomalyZScoreClassName(3.2)).toContain("bg-yellow-100");
  });
});
