// @vitest-environment node
import { describe, expect, it } from "vitest";
import { dayKey, formatDay, formatRelativeTime } from "@/lib/format-time";

const now = new Date(2026, 9, 21, 15, 0, 0).getTime();

describe("shared time format", () => {
  it("reads recent times relative and older ones as one absolute style", () => {
    expect(formatRelativeTime(now - 20_000, now)).toBe("just now");
    expect(formatRelativeTime(now - 5 * 60_000, now)).toBe("5 minutes ago");
    expect(formatRelativeTime(now - 3 * 3_600_000, now)).toBe("3 hours ago");
    const older = new Date(now - 2 * 86_400_000);
    expect(formatRelativeTime(older, now)).toBe(new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(older));
    expect(formatRelativeTime("not a time", now)).toBe("");
  });

  it("names calendar days for grouping", () => {
    expect(formatDay(new Date(2026, 9, 21, 0, 5), now)).toBe("Today");
    expect(formatDay(new Date(2026, 9, 20, 23, 55), now)).toBe("Yesterday");
    expect(formatDay(new Date(2026, 9, 19, 12), now)).toContain("19");
    expect(formatDay(new Date(2025, 9, 19, 12), now)).toContain("2025");
    expect(dayKey(new Date(2026, 9, 21, 0, 5))).toBe(dayKey(new Date(2026, 9, 21, 23, 55)));
    expect(dayKey(new Date(2026, 9, 21, 0, 5))).not.toBe(dayKey(new Date(2026, 9, 20, 23, 55)));
  });
});
