// @vitest-environment node
import { describe, expect, it } from "vitest";
import { excursions } from "@/features/charts/exceedance";

describe("excursions past a limit", () => {
  it("starts and ends each stretch where the line crosses the limit, not at the nearest value", () => {
    const { above } = excursions([
      { time: 0, value: 0, margin: -1 }, { time: 10, value: 2, margin: 1 }, { time: 20, value: 0, margin: -1 },
    ], ["above"]);
    expect(above).toEqual([[5, 1], [10, 2], [15, 1], [20, null]]);
  });

  it("joins one kind into the next at the value they share, and leaves gaps and missing limits alone", () => {
    const { quiet, alarm } = excursions([
      { time: 0, value: 2, margin: 1, kind: "quiet" }, { time: 1, value: 3, margin: 2, kind: "alarm" },
      { time: 2, value: null, margin: null }, { time: 3, value: 3, margin: null },
    ], ["quiet", "alarm"]);
    expect(quiet).toEqual([[0, 2], [1, null]]);
    expect(alarm).toEqual([[0, 2], [1, 3], [2, null]]);
  });
});
