import { describe, expect, it } from "vitest";
import { safeServiceReturn } from "@/features/catalogue/collectionRules";

describe("source setup return destinations", () => {
  it("preserves same-origin legacy and saved pipeline setup routes", () => {
    for (const path of [
      "/?create=monitoring&target=room",
      "/?pipeline=design&revision=published&replace=previous",
    ])
      expect(safeServiceReturn(path)).toBe(path);
  });
  it("rejects missing, external, unrelated, and incomplete destinations", () => {
    expect(safeServiceReturn(null)).toBe("/");
    for (const path of [
      "https://elsewhere.example/?pipeline=design",
      "//elsewhere.example/?pipeline=design",
      "/sources?pipeline=design",
      "/?view=pipelines",
      "/?pipeline=",
    ])
      expect(safeServiceReturn(path)).toBe("/");
  });
});
