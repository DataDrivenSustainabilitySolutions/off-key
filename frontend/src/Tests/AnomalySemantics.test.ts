import { describe, expect, it } from "vitest";

import {
  formatAnomalyTailProbability,
  getAnomalyTailProbabilityClassName,
} from "../lib/anomaly-semantics";

describe("anomaly semantics formatting", () => {
  it("formats anomaly value as tail-probability text", () => {
    expect(formatAnomalyTailProbability(0.004237)).toBe("0.0042");
  });

  it("uses red severity styling for tiny tail probability", () => {
    expect(getAnomalyTailProbabilityClassName(0.0008)).toContain("bg-red-100");
  });

  it("uses orange severity styling for alpha-level tail probability", () => {
    expect(getAnomalyTailProbabilityClassName(0.0042)).toContain("bg-orange-100");
  });

  it("uses yellow severity styling for larger tail probability", () => {
    expect(getAnomalyTailProbabilityClassName(0.03)).toContain("bg-yellow-100");
  });
});
