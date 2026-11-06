import { describe, expect, it } from "vitest";
import { datasetChartOption } from "@/features/dojo/dojo-chart";
import { formatDuration, readPages, runState, suggestBindings } from "@/features/dojo/model";
import type { DatasetSeriesView } from "@/types/dojo.generated";

const series = (id: string, name: string, unit: string | null = null): DatasetSeriesView => ({
  id, name, unit, position: 0, reading_id: null, point_count: 1, start_at: null, end_at: null });

describe("Dojo model", () => {
  it("binds a slot by name first, then by unit, then by order", () => {
    const available = [series("s1", "Temperature", "°C"), series("s2", "Voltage", "V"), series("s3", "Spare")];
    expect(suggestBindings([
      { id: "voltage", label: "Line voltage", unit: "V" },
      { id: "temperature", label: "Temperature", unit: null },
      { id: "other", label: "Other", unit: null },
    ], available)).toEqual({ temperature: "s1", voltage: "s2", other: "s3" });
  });

  it("leaves a slot unbound when every series is taken", () => {
    expect(suggestBindings([{ id: "a", label: "A" }, { id: "b", label: "B" }], [series("s1", "x")])).toEqual({ a: "s1" });
  });

  it("reads pages up to a limit and says when it stopped early", async () => {
    const pages: Record<string, { items: number[]; next_after: string | null }> = {
      start: { items: [1, 2], next_after: "a" }, a: { items: [3, 4], next_after: "b" }, b: { items: [5], next_after: null },
    };
    const fetch = async (after: string | undefined) => pages[after ?? "start"]!;
    await expect(readPages(fetch, 10)).resolves.toEqual({ items: [1, 2, 3, 4, 5], truncated: false });
    await expect(readPages(fetch, 3)).resolves.toEqual({ items: [1, 2, 3], truncated: true });
  });

  it("names durations in the largest readable unit", () => {
    expect([12, 90, 5400, 200_000].map(formatDuration)).toEqual(["12 s", "1.5 min", "1.5 h", "2.3 d"]);
    expect(formatDuration(null)).toBe("–");
  });

  it("shows a running run's progress", () => {
    expect(runState({ status: "running", points_read: 250, points_total: 1000 })).toEqual({ label: "Running 25%", tone: "warning" });
    expect(runState({ status: "failed", points_read: 0, points_total: 0 }).tone).toBe("danger");
  });
});

describe("Dojo chart", () => {
  const colors = { foreground: "#000", mutedForeground: "#666", border: "#ddd", popover: "#fff", popoverForeground: "#000",
    muted: "#eee", primary: "#3a7e72", seriesPalette: ["#111", "#222", "#333"], alarmBoundary: "#b00", alarmFill: "#b001" };

  it("shades labels behind the values", () => {
    const option = datasetChartOption({ colors, timeZone: "UTC",
      series: [{ id: "s1", name: "Voltage", unit: "V", points: [[0, 1], [60_000, 2]] }],
      labels: [{ id: "l1", start: 10_000, end: 20_000, note: "fault" }] });
    const [line] = option.series as Array<{ name: string; markArea: { data: unknown[] } }>;
    expect(line!.name).toBe("Voltage (V)");
    expect(line!.markArea.data).toEqual([[{ xAxis: 10_000, name: "fault" }, { xAxis: 20_000 }]]);
    expect(option.grid).toHaveLength(1);
  });

  it("gives each run's alarms their own row under the values", () => {
    const option = datasetChartOption({ colors, timeZone: "UTC", labels: [],
      series: [{ id: "s1", name: "Voltage", unit: null, points: [[0, 1]] }],
      alarms: [{ id: "r1", name: "Forest", times: [5, 9] }, { id: "r2", name: "Baseline", times: [] }] });
    const marks = (option.series as Array<{ id: string; data: unknown[] }>).filter(item => item.id.startsWith("alarms:"));
    expect(marks.map(item => item.data)).toEqual([[[5, "Forest"], [9, "Forest"]], []]);
    expect(option.grid).toHaveLength(2);
    expect((option.yAxis as Array<{ data?: string[] }>)[1]!.data).toEqual(["Forest", "Baseline"]);
    // Both rows span the same time, so a mark sits under its value.
    expect((option.xAxis as Array<{ min?: number; max?: number }>).map(axis => [axis.min, axis.max])).toEqual([[0, 9], [0, 9]]);
  });

  it("puts a second unit on its own axis", () => {
    const option = datasetChartOption({ colors, timeZone: "UTC", labels: [], series: [
      { id: "v", name: "Voltage", unit: "V", points: [[0, 230]] }, { id: "i", name: "Current", unit: "A", points: [[0, 12]] },
      { id: "u", name: "Other voltage", unit: "V", points: [[0, 231]] }] });
    expect((option.series as Array<{ yAxisIndex: number }>).map(item => item.yAxisIndex)).toEqual([0, 1, 0]);
    expect((option.yAxis as Array<{ position: string }>).map(axis => axis.position)).toEqual(["left", "right"]);
  });
});
