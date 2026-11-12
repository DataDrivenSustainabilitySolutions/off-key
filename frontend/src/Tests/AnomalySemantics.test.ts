// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  formatAnomalyTailProbability,
  formatAnomalyValue,
  isProbabilityAnomalyValue,
} from "../lib/anomaly-semantics";

describe("anomaly semantics formatting", () => {
  it("formats anomaly value as tail-probability text", () => {
    expect(formatAnomalyTailProbability(0.004237)).toBe("0.0042");
  });

  it("preserves very small nonzero probabilities", () => {
    expect(formatAnomalyTailProbability(0.000032)).toBe('3.20e-5');
    expect(formatAnomalyTailProbability(0)).toBe('0.0000');
  });

  it("treats conformal p-values as probability anomaly values", () => {
    expect(isProbabilityAnomalyValue("conformal_pvalue")).toBe(true);
    expect(formatAnomalyValue(0.0031, "conformal_pvalue")).toBe("0.0031");
  });
});
