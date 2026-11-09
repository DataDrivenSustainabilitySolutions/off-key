import { beforeEach, describe, expect, it } from "vitest";
import { migrateBrandStorage } from "../lib/migrate-brand-storage";

describe("brand storage migration", () => {
  beforeEach(() => localStorage.clear());
  it("moves old state, preserves newer state and leaves unrelated keys alone", () => {
    localStorage.setItem("off-key:draft:1:pipeline", '{"name":"draft"}');
    localStorage.setItem("off-key:details:chart-navigation", "linked");
    localStorage.setItem("aberration:details:chart-navigation", "independent");
    localStorage.setItem("unrelated", "keep");
    migrateBrandStorage(localStorage);
    migrateBrandStorage(localStorage);
    expect(localStorage.getItem("aberration:draft:1:pipeline")).toBe('{"name":"draft"}');
    expect(localStorage.getItem("aberration:details:chart-navigation")).toBe("independent");
    expect(localStorage.getItem("off-key:draft:1:pipeline")).toBeNull();
    expect(localStorage.getItem("off-key:details:chart-navigation")).toBeNull();
    expect(localStorage.getItem("unrelated")).toBe("keep");
  });
  it("retains the original if writing the replacement fails", () => {
    const values = new Map([["off-key:draft:1:pipeline", "draft"]]);
    const storage = {
      length: 1, key: () => [...values.keys()][0] ?? null,
      getItem: (key: string) => values.get(key) ?? null,
      setItem: () => { throw new Error("Quota exceeded"); },
      removeItem: (key: string) => { values.delete(key); },
      clear: () => values.clear(),
    };
    expect(() => migrateBrandStorage(storage)).toThrow("Quota exceeded");
    expect(values.get("off-key:draft:1:pipeline")).toBe("draft");
  });
});
