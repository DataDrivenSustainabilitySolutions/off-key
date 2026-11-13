// @vitest-environment node
import { describe, expect, it } from "vitest";
import { combineHistory, historyBandSeries, historyChartData, historyInterval, presentHistory } from "@/features/charts/history-presentation";
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

  it("draws each mean across its whole interval and breaks the line and band across an empty one", () => {
    const history = presentHistory([...data.slice(0, 20), ...data.slice(100, 120)], { mode: "auto", windowMs: 5000 }, 100);
    const display = historyChartData(history);
    // Each run reaches the outer edges of its buckets, so a bucket between two gaps still has a width.
    expect(display.map(point => point.value)).toEqual([
      [START, 1], [START + 2500, 1], [START + 5000, 1], [START + 7500, null],
      [START + 10000, 1], [START + 10950, 1], [START + 11900, 1],
    ]);
    const bands = historyBandSeries("voltage", display, "#3A7E72", 0);
    expect(bands[0]!.data).toEqual([[START, 0], [START + 2500, 0], [START + 5000, 0], [START + 7500, null],
      [START + 10000, 0], [START + 10950, 0], [START + 11900, 0]]);
    expect(bands[1]).toMatchObject({ stackStrategy: "all", silent: true });
  });

  it("joins a clipped or still-filling edge bucket with its neighbour for display only", () => {
    // 5 s buckets of 50 readings; the newest holds 3, far too few for a steady mean.
    const live = presentHistory(data.slice(0, 153).map(([time, value], index): TimeValue => [time, index >= 150 ? 100 : value]),
      { mode: "auto", windowMs: 5000 }, 100);
    expect(live.points.map(point => point.count)).toEqual([50, 50, 50, 3]);
    expect(live.points[3]!.value).toBe(100);
    const display = historyChartData(live);
    const last = display[display.length - 1]!;
    expect(last.summary).toMatchObject({ count: 53, minimum: 0, maximum: 100, start: live.points[2]!.start, end: live.points[3]!.end });
    expect(last.summary!.value).toBeCloseTo((50 * 1 + 3 * 100) / 53);
    expect(display.filter(point => point.summary).map(point => point.summary!.count)).not.toContain(3);
  });

  it("chooses one readable interval for a span, as the server does", () => {
    expect(historyInterval(3_600_000, 300)).toBe(15_000);
    expect(historyInterval(3_600_000, 300, 60_000)).toBe(60_000);
    expect(historyInterval(7 * 86_400_000, 100)).toBe(7_200_000);
    expect(historyInterval(400 * 86_400_000, 100)).toBe(4 * 86_400_000);
    const sparse: TimeValue[] = [[START, 1], [START + 60_000, 2]];
    expect(presentHistory(sparse, { mode: "auto" }, 100, undefined, 15_000).representation).toBe("raw");
    expect(presentHistory(data, { mode: "auto" }, 100, undefined, 15_000)).toMatchObject({ representation: "mean", interval_ms: 15_000 });
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
    // The interval heads the tooltip once, however many readings share it.
    expect(tooltip.split("\n")[0]).toMatch(/12:00:00.*12:00:05.*UTC$/);
    expect(tooltip.split("\n")).toHaveLength(3);
  });

  it("keeps a mean short and a negative range readable", () => {
    const summary = { timestamp: "2026-11-11T12:00:02.500Z", value: -2.1543219, minimum: -3.07612, maximum: -1.42231, count: 15,
      start: "2026-11-11T12:00:00.000Z", end: "2026-11-11T12:00:05.000Z" };
    const tooltip = formatTelemetryTooltip({ seriesId: "telemetry", seriesName: "Power", value: [START + 2500, summary.value], data: { summary } },
      "UTC", new Map([["Power", "kW"]]));
    expect(tooltip).toContain("Power: -2.154 kW (mean)");
    expect(tooltip).toContain("Min–max: -3.076 to -1.422 kW · 15 readings");
  });
});
