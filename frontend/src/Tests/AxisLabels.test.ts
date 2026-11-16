import { describe, expect, it } from "vitest";

import { compactAxis, formatAxisValue, valueAxisGutter } from "@/features/charts/axis-labels";

describe("value axis labels", () => {
  it("abbreviates large values without merging neighbouring ticks", () => {
    expect([5_000_000, 5_010_000, 5_020_000, 5_050_000].map(value => formatAxisValue(value, "en-US")))
      .toEqual(["5M", "5.01M", "5.02M", "5.05M"]);
    expect([10_100, 10_110, 10_120].map(value => formatAxisValue(value, "en-US")))
      .toEqual(["10.1K", "10.11K", "10.12K"]);
    expect(formatAxisValue(2_400_000_000, "en-US")).toBe("2.4B");
  });

  it("writes values in full on an axis that does not abbreviate", () => {
    expect([0, 3_000, 10_120, 99_500].map(value => formatAxisValue(value, "en-US", false)))
      .toEqual(["0", "3,000", "10,120", "99,500"]);
  });

  it("keeps small, negative and noisy values readable", () => {
    expect(formatAxisValue(0.0025, "en-US")).toBe("0.0025");
    expect(formatAxisValue(0.1 + 0.2, "en-US")).toBe("0.3");
    expect(formatAxisValue(-1_250_000, "en-US")).toBe("-1.25M");
    expect(formatAxisValue(-250, "en-US")).toBe("-250");
    expect(formatAxisValue(0.00000015, "en-US")).toBe("1.5e-7");
    expect(formatAxisValue(2e18, "en-US")).toBe("2e18");
  });

  it("follows the reader's locale", () => {
    expect(formatAxisValue(5_010_000, "de-DE")).toBe("5,01\u00a0Mio.");
    expect(formatAxisValue(10_120, "de-DE", false)).toBe("10.120");
  });

  it("abbreviates an axis once its values reach six figures", () => {
    expect(compactAxis([12, 99_999, null])).toBe(false);
    expect(compactAxis([12, -100_000])).toBe(true);
    expect(compactAxis([undefined, 5_032_961.67])).toBe(true);
  });

  it("sizes the gutter from the widest label, in steps and never below its minimum", () => {
    expect(valueAxisGutter([])).toBe(32);
    expect(valueAxisGutter([10, 20])).toBe(40);
    expect(valueAxisGutter([33])).toBe(48);
    expect(valueAxisGutter([30, 34])).toBe(valueAxisGutter([34]));
  });
});
