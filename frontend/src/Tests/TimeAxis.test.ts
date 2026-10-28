// @vitest-environment node
import { describe, expect, it } from "vitest";
import { isLocalMidnight, localMidnights, timeAxisLabelFormatter } from "@/features/charts/time-axis";
import { buildTelemetryChartModel, buildTelemetryChartOption } from "@/features/charts/telemetry-chart";

const at = (iso: string) => Date.parse(iso);

describe("local day breaks", () => {
  it("finds each midnight in the zone, across a daylight-saving change", () => {
    // Berlin leaves summer time on 25 October 2026: that day lasts 25 hours.
    expect(localMidnights(at("2026-10-24T12:00:00Z"), at("2026-10-27T12:00:00Z"), "Europe/Berlin")).toEqual([
      at("2026-10-24T22:00:00Z"), at("2026-10-25T23:00:00Z"), at("2026-10-26T23:00:00Z"),
    ]);
    expect(localMidnights(at("2026-10-24T12:00:00Z"), at("2026-10-25T12:00:00Z"), "UTC")).toEqual([at("2026-10-25T00:00:00Z")]);
  });

  it("excludes a midnight at the start, includes one at the end, and draws none when they would crowd", () => {
    expect(localMidnights(at("2026-10-25T00:00:00Z"), at("2026-10-26T00:00:00Z"), "UTC")).toEqual([at("2026-10-26T00:00:00Z")]);
    expect(localMidnights(at("2026-01-01T00:00:00Z"), at("2026-12-31T00:00:00Z"), "UTC")).toEqual([]);
    expect(localMidnights(at("2026-10-25T08:00:00Z"), at("2026-10-25T09:00:00Z"), "UTC")).toEqual([]);
  });

  it("recognises midnight in the zone, not in UTC", () => {
    expect(isLocalMidnight(at("2026-10-27T23:00:00Z"), "Europe/Berlin")).toBe(true);
    expect(isLocalMidnight(at("2026-10-28T00:00:00Z"), "Europe/Berlin")).toBe(false);
  });
});

describe("time axis labels", () => {
  it("shows seconds only over a few minutes and names the day at midnight", () => {
    const minutes = timeAxisLabelFormatter("UTC", "en-US", 5 * 60_000);
    const hours = timeAxisLabelFormatter("UTC", "en-US", 24 * 3_600_000);
    expect(minutes(at("2026-10-28T14:03:12Z"))).toBe("14:03:12");
    expect(hours(at("2026-10-28T14:03:12Z"))).toBe("14:03");
    expect(hours(at("2026-10-28T00:00:00Z"))).toBe("{day|Wed, Oct 28}");
  });

  it("keeps the date line on the standard layout", () => {
    const standard = timeAxisLabelFormatter("UTC", "en-US", 24 * 3_600_000, true);
    expect(standard(at("2026-10-28T14:00:00Z"))).toBe("Oct 28\n14:00");
    expect(standard(at("2026-10-28T00:00:00Z"))).toBe("{day|Wed, Oct 28}\n00:00");
  });
});

describe("day breaks on the chart", () => {
  const colors = { foreground: "#111", mutedForeground: "#666", border: "#ddd", popover: "#fff", popoverForeground: "#111", muted: "#eee", primary: "#0a7" };
  const option = (times: string[]) => buildTelemetryChartOption({
    model: buildTelemetryChartModel({ telemetryName: "Voltage", telemetryColor: "#2563eb", anomalyMarkers: [], detectors: [],
      telemetry: times.map((time, index) => [at(time), index]) }),
    viewport: { mode: "live" }, timeZone: "UTC", colors, accessibleDescription: "Voltage", locale: "en-US", layout: "compact",
  }) as unknown as { series: Array<{ markLine?: { data: Array<{ xAxis: number }> } }>;
    xAxis: Array<{ axisLabel: { rich?: Record<string, unknown>; formatter: (value: number) => string } }> };

  it("rules each midnight in the visible span with a silent dashed line", () => {
    const chart = option(["2026-10-26T18:00:00Z", "2026-10-28T06:00:00Z"]);
    expect(chart.series[0]?.markLine).toMatchObject({ silent: true, data: [
      { xAxis: at("2026-10-27T00:00:00Z"), lineStyle: { type: "dashed" } },
      { xAxis: at("2026-10-28T00:00:00Z"), lineStyle: { type: "dashed" } },
    ] });
    expect(chart.xAxis[0]?.axisLabel.rich).toHaveProperty("day");
    expect(chart.xAxis[0]?.axisLabel.formatter(at("2026-10-27T12:00:00Z"))).toBe("12:00");
  });

  it("adds nothing within a single day", () => {
    expect(option(["2026-10-28T08:00:00Z", "2026-10-28T09:00:00Z"]).series[0]?.markLine).toBeUndefined();
  });
});
