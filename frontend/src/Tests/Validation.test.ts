import { describe, expect, it } from "vitest";

import { validateNumeric, validateUserId } from "../lib/validation";

describe("validation utilities", () => {
  it("rejects partial and fractional user IDs", () => {
    expect(validateUserId("42abc").isValid).toBe(false);
    expect(validateUserId(4.2).isValid).toBe(false);
    expect(validateUserId("42").isValid).toBe(true);
  });

  it("rejects partial and blank numeric input", () => {
    expect(validateNumeric("12abc").isValid).toBe(false);
    expect(validateNumeric("").isValid).toBe(false);
    expect(validateNumeric("12.5").isValid).toBe(true);
  });
});
