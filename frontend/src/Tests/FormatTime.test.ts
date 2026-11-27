// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { dayKey, formatDay, formatRelativeTime } from "@/lib/format-time";

const now = new Date(2026, 9, 21, 15, 0, 0).getTime();
const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("shared time format", () => {
  it("reads English whatever the browser's language", async () => {
    const locales: unknown[] = [];
    const record = <T extends object>(Format: T) => new Proxy(Format, {
      construct: (target, args) => { locales.push(args[0]); return Reflect.construct(target as never, args); } });
    vi.stubGlobal("Intl", { ...Intl, DateTimeFormat: record(Intl.DateTimeFormat), RelativeTimeFormat: record(Intl.RelativeTimeFormat) });
    vi.resetModules();
    const { formatRelativeTime: format } = await import("@/lib/format-time");
    expect(locales.length).toBeGreaterThan(0);
    expect(locales.every(locale => locale === "en")).toBe(true);
    expect(format(now - 5 * 60_000, now)).toBe("5 minutes ago");
    expect(format(now - 12_000, now, "elapsed")).toBe("12 seconds ago");
  });

  it("reads recent times relative and older ones as one absolute style", () => {
    expect(formatRelativeTime(now - 20_000, now)).toBe("just now");
    expect(formatRelativeTime(now - 5 * 60_000, now)).toBe(relative.format(-5, "minute"));
    expect(formatRelativeTime(now - 3 * 3_600_000, now)).toBe(relative.format(-3, "hour"));
    const older = new Date(now - 2 * 86_400_000);
    expect(formatRelativeTime(older, now)).toBe(new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(older));
    expect(formatRelativeTime("not a time", now)).toBe("");
  });

  it("shows elapsed seconds and keeps older readings relative", () => {
    expect(formatRelativeTime(now - 59_999, now, "elapsed")).toBe(relative.format(-59, "second"));
    expect(formatRelativeTime(now - 60_000, now, "elapsed")).toBe(relative.format(-1, "minute"));
    const elapsedDays = new Intl.RelativeTimeFormat("en", { numeric: "always" });
    expect(formatRelativeTime(now - 2 * 86_400_000, now, "elapsed")).toBe(elapsedDays.format(-2, "day"));
  });

  it("names calendar days for grouping", () => {
    expect(formatDay(new Date(2026, 9, 21, 0, 5), now).toLocaleLowerCase()).toBe(relative.format(0, "day"));
    expect(formatDay(new Date(2026, 9, 20, 23, 55), now).toLocaleLowerCase()).toBe(relative.format(-1, "day"));
    expect(formatDay(new Date(2026, 9, 19, 12), now)).toContain("19");
    expect(formatDay(new Date(2025, 9, 19, 12), now)).toContain("2025");
    expect(dayKey(new Date(2026, 9, 21, 0, 5))).toBe(dayKey(new Date(2026, 9, 21, 23, 55)));
    expect(dayKey(new Date(2026, 9, 21, 0, 5))).not.toBe(dayKey(new Date(2026, 9, 20, 23, 55)));
  });
});
