// @vitest-environment node
import { describe, expect, it } from "vitest";
import { combineHistory, historyBandSeries, historyChartData, presentHistory } from "@/features/charts/history-presentation";
import { formatTelemetryTooltip } from "@/features/charts/telemetry-chart";
import type { TimeValue } from "@/features/charts/telemetry-data";

const START = Date.parse("2026-11-11T12:00:00Z");
const data = Array.from({ length: 600 }, (_, i): TimeValue => [START + i * 100, i % 10 === 0 ? 10 : 0]);

describe("history presentation", () => {
  it("computes the actual mean, preserving a brief spike and its sample count", () => {
    const history = presentHistory(data, { mode: "auto", windowMs: 5000 }, 100);
    expect(history.representation).toBe("mean");
    expect(history.points[0]).toMatchObject({ value: 1, minimum: 0, maximum: 10, count: 50 });
    expect(history.points.reduce((count, point) => count + point.count!, 0)).toBe(600);
    expect(data[0]).toEqual([START, 10]);
  });

  it("shows every original sample in Raw and returns automatically to raw at close zoom", () => {
    const raw = presentHistory(data, { mode: "raw", windowMs: 60000 }, 10);
    expect(raw.points).toHaveLength(600);
    expect(raw.points[1]).toEqual({ timestamp: "2026-11-11T12:00:00.100Z", value: 0 });
    expect(presentHistory(data, { mode: "auto" }, 100, [START, START + 1000]).representation).toBe("raw");
  });

  it("keeps closed epoch-aligned buckets stable during a live refresh", () => {
    const first = presentHistory(data, { mode: "auto", windowMs: 5000 }, 100, [START + 123, START + 55000]);
    const next = presentHistory(data, { mode: "auto", windowMs: 5000 }, 100, [START + 456, START + 56000]);
    expect(first.points[1]).toEqual(next.points[1]);
  });

  it("breaks the mean and observed-range band across an empty time bucket", () => {
    const history = presentHistory([...data.slice(0, 20), ...data.slice(100, 120)], { mode: "auto", windowMs: 5000 }, 100);
    const display = historyChartData(history);
    expect(display).toHaveLength(3);
    expect(display[1]!.value[1]).toBeNull();
    const bands = historyBandSeries("voltage", display, "#3A7E72", 0);
    expect(bands[0]!.data).toEqual([[START + 2500, 0], [START + 6725, null], [START + 10950, 0]]);
    expect(bands[1]).toMatchObject({ stackStrategy: "all", silent: true });
  });

  it("replaces an averaged viewport with raw detail without changing overview extent", () => {
    const overview = presentHistory(data, { mode: "auto", windowMs: 5000 }, 100);
    const range = { startMs: START + 10000, endMs: START + 11000 };
    const detail = presentHistory(data, { mode: "raw" }, 100, [range.startMs, range.endMs]);
    const merged = combineHistory(overview, detail, range);
    expect(merged.extent).toEqual(overview.extent);
    expect(merged.points.filter(point => Date.parse(point.timestamp) >= range.startMs && Date.parse(point.timestamp) <= range.endMs)).toEqual(detail.points);
    expect(merged.representation).toBe("raw");
  });

  it("labels means, ranges, counts and intervals explicitly in the tooltip", () => {
    const history = presentHistory(data, { mode: "auto", windowMs: 5000 }, 100);
    const point = historyChartData(history)[0]!;
    const tooltip = formatTelemetryTooltip({ seriesId: "telemetry", seriesName: "Voltage", value: point.value, data: point }, "UTC", new Map([["Voltage", "V"]]));
    expect(tooltip).toContain("Voltage: 1 V (mean)");
    expect(tooltip).toContain("Min–max: 0–10 V · 50 readings");
    expect(tooltip).toContain("12:00:05");
  });
});
