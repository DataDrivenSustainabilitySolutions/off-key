import { describe, expect, it } from "vitest";

import {
  formatLastSeen,
  isWithinTimeRange,
  formatTimestamp,
  timestampsAreClose,
  groupTimestampsIntoRanges,
} from "../lib/time-utils";

describe("time utils", () => {
  it("returns an empty array for no timestamps", () => {
    expect(groupTimestampsIntoRanges([])).toEqual([]);
  });

  it("sorts unsorted timestamps before grouping by default", () => {
    const ranges = groupTimestampsIntoRanges([
      "2026-07-09T12:05:00.000Z",
      "2026-07-09T12:00:00.000Z",
      "2026-07-09T12:10:00.000Z",
    ]);

    expect(ranges).toEqual([
      { start: "2026-07-09T12:00:00.000Z", end: "2026-07-09T12:10:00.000Z" },
    ]);
  });

  it("formats short timestamps with zero-padded date and time components", () => {
    const timestamp = "2026-07-09T12:00:05.123Z";
    const date = new Date(timestamp);
    const expected = `${String(date.getDate()).padStart(2, "0")}.${String(
      date.getMonth() + 1,
    ).padStart(2, "0")}, ${String(date.getHours()).padStart(2, "0")}:${String(
      date.getMinutes(),
    ).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;

    expect(formatTimestamp(timestamp)).toBe(expected);
  });

  it("formats long timestamps in the en-US short+medium locale style", () => {
    const timestamp = "2026-07-09T12:00:05.123Z";
    const date = new Date(timestamp);
    const expected = date.toLocaleString("en-US", {
      dateStyle: "short",
      timeStyle: "medium",
    });

    expect(formatTimestamp(timestamp, "long")).toBe(expected);
  });

  it("keeps caller-provided ordering when areAlreadySorted is true", () => {
    const ranges = groupTimestampsIntoRanges(
      [
        "2026-07-09T12:00:00.000Z",
        "2026-07-09T12:06:00.000Z",
      ],
      60_000,
      true
    );

    expect(ranges).toEqual([
      { start: "2026-07-09T12:00:00.000Z", end: "2026-07-09T12:00:00.000Z" },
      { start: "2026-07-09T12:06:00.000Z", end: "2026-07-09T12:06:00.000Z" },
    ]);
  });

  it("does not mutate the input array when sorting", () => {
    const timestamps = [
      "2026-07-09T12:05:00.000Z",
      "2026-07-09T12:00:00.000Z",
    ];
    const expected = [...timestamps];

    groupTimestampsIntoRanges(timestamps);

    expect(timestamps).toEqual(expected);
  });

  it("splits ranges when gap exceeds max gap and merges when it does not", () => {
    const spaced = groupTimestampsIntoRanges(
      [
        "2026-07-09T12:00:00.000Z",
        "2026-07-09T12:07:00.000Z",
      ],
      5 * 60 * 1000
    );
    const merged = groupTimestampsIntoRanges(
      [
        "2026-07-09T12:00:00.000Z",
        "2026-07-09T12:07:00.000Z",
      ],
      8 * 60 * 1000
    );

    expect(spaced).toEqual([
      { start: "2026-07-09T12:00:00.000Z", end: "2026-07-09T12:00:00.000Z" },
      { start: "2026-07-09T12:07:00.000Z", end: "2026-07-09T12:07:00.000Z" },
    ]);
    expect(merged).toEqual([
      { start: "2026-07-09T12:00:00.000Z", end: "2026-07-09T12:07:00.000Z" },
    ]);
  });

  it("returns true only when timestamp is inside inclusive date range", () => {
    const timestamp = "2026-07-09T12:00:30.000Z";
    const from = new Date("2026-07-09T12:00:00.000Z");
    const to = new Date("2026-07-09T12:01:00.000Z");

    expect(isWithinTimeRange(timestamp, from, to)).toBe(true);
    expect(isWithinTimeRange("2026-07-09T11:59:59.000Z", from, to)).toBe(false);
    expect(isWithinTimeRange("2026-07-09T12:01:01.000Z", from, to)).toBe(false);
  });

  it("formats missing/invalid last-seen values as Never", () => {
    expect(formatLastSeen(undefined)).toBe("Never");
    expect(formatLastSeen(null)).toBe("Never");
    expect(formatLastSeen("not-a-date")).toBe("Never");
  });

  it("treats timestamps within tolerance as close", () => {
    const base = "2026-07-09T12:00:00.000Z";
    expect(timestampsAreClose(base, "2026-07-09T12:00:00.500Z", 1_000)).toBe(true);
    expect(timestampsAreClose(base, "2026-07-09T12:00:01.100Z", 1_000)).toBe(false);
  });
});
