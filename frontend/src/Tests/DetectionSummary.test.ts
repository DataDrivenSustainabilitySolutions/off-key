// @vitest-environment node
import { describe, expect, it } from "vitest";
import { summarizeDetection } from "@/features/charts/detection-summary";
import type { DetectorInputSeries } from "@/features/charts/detector-inputs";
import {
  buildMonitoringChartOption,
  formatTelemetryTooltip,
  type ChartThemeColors,
  type MonitoringChartModel,
} from "@/features/charts/telemetry-chart";
import type { DetectionObservation, SecondaryChartSeries } from "@/features/charts/telemetry-detectors";
import type { MonitoringChartReading } from "@/features/charts/types";
import { formatMonitoringObservationTooltip } from "@/features/charts/monitoring-tooltip";

const START = Date.parse("2026-11-11T12:00:00Z");
const colors: ChartThemeColors = { foreground: "#111", mutedForeground: "#666", border: "#ddd", popover: "#fff",
  popoverForeground: "#111", muted: "#eee", primary: "#3a7e72", alarmBoundary: "#dc2626", alarmFill: "rgba(220, 38, 38, 0.12)" };

const observed = (offsetMs: number, value: number | null, alarm = false): DetectionObservation => ({
  sequenceNumber: offsetMs, timeMs: START + offsetMs, value, threshold: 0.6, alarmActive: alarm, alarmFired: alarm,
  logValue: null, isInfinite: false,
});
const score = (observations: DetectionObservation[], overrides: Partial<SecondaryChartSeries> = {}): SecondaryChartSeries => ({
  id: "adaptive-score:svc", serviceId: "svc", name: "Anomaly score", pane: "adaptive",
  data: observations.map(observation => ({ value: [observation.timeMs, observation.value], observation })),
  thresholdRegions: [], overflow: [], latestObservation: observations[observations.length - 1]!,
  bounds: { minimum: 0, maximum: 1 }, ...overrides,
});
/** One result every 100 ms for ten seconds; `special` replaces the ones a test is about. */
const steady = (special: Record<number, DetectionObservation> = {}) =>
  Array.from({ length: 100 }, (_, index) => special[index] ?? observed(index * 100, 0.3 + (index % 10) / 100));
const reading = (overrides: Partial<MonitoringChartReading> = {}): MonitoringChartReading => ({
  id: "reading:voltage", name: "Voltage", unit: "V", color: "#3a7e72", data: [[START, 400], [START + 1000, 401]],
  pendingTelemetry: [], anomalyMarkers: [], ...overrides,
});
const option = (model: Partial<MonitoringChartModel>, layout: "monitoring" | "compact" = "monitoring") => buildMonitoringChartOption({
  model: { readings: [reading()], secondarySeries: [], range: {}, extent: [START, START + 10_000], ...model },
  colors, timeZone: "UTC", accessibleDescription: "Chart", layout, viewport: { mode: "live" },
});
type Marks = { markArea: { data: unknown; itemStyle: { color: string } }; markLine: { data: unknown };
  markPoint: { data: Array<{ name: string; coord: number[] }> } };
const seriesOf = (built: ReturnType<typeof option>, id: string) =>
  (built.series as Array<{ id?: string }>).find(series => series.id === id) as Marks | undefined;

describe("detection follows a reading into its intervals", () => {
  it("keeps each interval's highest recorded result, and an alarm over a higher quiet score", () => {
    const alarmed = observed(3200, 0.7, true), louder = observed(3500, 0.9);
    const series = score(steady({ 32: alarmed, 35: louder }));
    const { secondarySeries: [summary] } = summarizeDetection({ secondarySeries: [series] }, 1000, 10);
    expect(summary!.data).toHaveLength(10);
    expect(summary!.data.every(point => point.peak?.count === 10)).toBe(true);
    // The kept point is the recorded observation itself: its time, threshold and inputs stay exact.
    expect(summary!.data[0]!.observation).toBe(series.data[9]!.observation);
    expect(summary!.data[0]!.value).toEqual([START + 900, 0.39]);
    expect(summary!.data[3]!.observation).toBe(alarmed);
    // The scale and the alarm zone are those of every result, so Auto and Raw share them.
    expect(summary).toMatchObject({ bounds: series.bounds, thresholdRegions: series.thresholdRegions, latestObservation: series.latestObservation });
  });

  it("breaks the line across an empty interval and leaves sparse series and Raw as recorded", () => {
    const paused = score(steady().filter((_, index) => index < 30 || index >= 60));
    const { secondarySeries: [summary] } = summarizeDetection({ secondarySeries: [paused] }, 1000, 10);
    expect(summary!.data.map(point => point.value[1] === null ? null : point.peak!.count))
      .toEqual([10, 10, 10, null, 10, 10, 10, 10]);
    expect(summary!.data[3]!.value[0]).toBe(START + 4500);

    const sparse = { secondarySeries: [score(steady().slice(0, 20))] };
    expect(summarizeDetection(sparse, 1000, 10)).toEqual(sparse);
    const dense = { secondarySeries: [score(steady())] };
    expect(summarizeDetection(dense, 0, 10)).toBe(dense);
    // Dense overall, yet the inspected window holds few enough results to show each one.
    expect(summarizeDetection(dense, 1000, 10, [START, START + 1500]).secondarySeries[0]).toBe(dense.secondarySeries[0]);
  });

  it("lets a still-filling newest interval join its neighbour instead of ending the line on one result", () => {
    const latest = observed(10_000, 0.05);
    const { secondarySeries: [summary] } = summarizeDetection({ secondarySeries: [score([...steady(), latest])] }, 1000, 10);
    expect(summary!.data).toHaveLength(10);
    expect(summary!.data[9]).toMatchObject({ value: [START + 9900, 0.39], peak: { count: 11 } });
  });

  it("keeps evidence above the plotted range ahead of any plotted value", () => {
    const beyond: DetectionObservation = { ...observed(3300, null, true), isInfinite: true };
    const observations = steady({ 33: beyond });
    const series = score(observations, { pane: "static", overflow: [
      { observation: beyond, boundary: "upper" }, { observation: observations[70]!, boundary: "lower" }] });
    const { secondarySeries: [summary] } = summarizeDetection({ secondarySeries: [series] }, 1000, 10);
    expect(summary!.data[3]!.observation).toBe(beyond);
    // A marker belongs to a kept result; the one a higher result replaced goes with it.
    expect(summary!.overflow).toEqual([{ observation: beyond, boundary: "upper" }]);
  });

  it("summarises a feature by its mean and range, and its forecast over the same intervals", () => {
    const input: DetectorInputSeries = { id: "input::duty", name: "duty",
      data: Array.from({ length: 100 }, (_, index) => [START + index * 100, index % 2 ? 0.1 : 0]),
      forecast: Array.from({ length: 100 }, (_, index) => [START + index * 100, 0.05, 0.03, index < 50 ? 0.07 : null]) };
    const { detectorInputs } = summarizeDetection({ secondarySeries: [], detectorInputs: [input] }, 1000, 10);
    const [summary] = detectorInputs!;
    expect(summary!.data).toHaveLength(10);
    expect(summary!.data[0]![0]).toBe(START + 500);
    expect(summary!.data[0]![1]).toBeCloseTo(0.05);
    expect(summary!.range![0]).toEqual([START + 500, 0, 0.1]);
    expect(summary!.forecast![0]![1]).toBeCloseTo(0.05);
    expect(summary!.forecast![0]![2]).toBeCloseTo(0.03);
    expect(summary!.forecast![9]![3]).toBeNull();
  });
});

describe("a summarised chart", () => {
  it("draws consecutive alarm results as one episode and joins those the width cannot separate", () => {
    const built = option({ readings: [reading({ alarmSpans: [
      [START + 1000, START + 1000], [START + 4000, START + 4500], [START + 4520, START + 5000], [START + 8000, START + 8600]] })] });
    const line = seriesOf(built, "reading:voltage")!;
    expect(line.markArea.data).toEqual([[{ xAxis: START + 4000 }, { xAxis: START + 5000 }], [{ xAxis: START + 8000 }, { xAxis: START + 8600 }]]);
    expect(line.markArea.itemStyle.color).toBe(colors.alarmFill);
    // One line where each episode began; a single alarm result is that line alone.
    expect(line.markLine.data).toEqual([{ xAxis: START + 1000 }, { xAxis: START + 4000 }, { xAxis: START + 8000 }]);
  });

  it("marks where a detector's alarm begins, not every result that keeps it up", () => {
    const observations = steady({ 40: observed(4000, 0.8, true), 41: observed(4100, 0.9, true), 42: observed(4200, 0.85, true),
      80: observed(8000, 0.7, true) });
    const built = option({ secondarySeries: [score(observations)] });
    const dots = seriesOf(built, "adaptive-score:svc")!.markPoint.data.filter(point => point.name === "Alarm decision");
    expect(dots.map(point => point.coord)).toEqual([[START + 4000, 0.8], [START + 8000, 0.7]]);
  });

  it("gives a value with no line to either side a dot, and a single value none of its own", () => {
    // A burst of five samples, then two that each stand alone between pauses.
    const display = { representation: "raw" as const, interval_ms: 0, sample_count: 7, extent: null, truncated: false,
      points: [0, 100, 200, 300, 400, 60_000, 120_000].map((offset, index) => ({ timestamp: new Date(START + offset).toISOString(), value: index })) };
    const built = option({ readings: [reading({ presentation: display })] });
    expect(seriesOf(built, "history-dot:reading:voltage")).toMatchObject({ type: "scatter", silent: true,
      data: [[START + 60_000, 5], [START + 120_000, 6]], tooltip: { show: false } });
    expect(seriesOf(option({ readings: [reading({ data: [[START, 400]] })] }), "history-dot:reading:voltage")).toBeUndefined();
  });

  it("keeps a burst of results visible when it falls into one interval", () => {
    // A score line draws no symbols, so the one result a burst is summarised to needs a dot.
    const burst = score(Array.from({ length: 50 }, (_, index) => observed(index * 10, 0.3 + index / 1000)));
    const { secondarySeries: [summary] } = summarizeDetection({ secondarySeries: [burst] }, 1000, 10);
    expect(summary!.data).toHaveLength(1);
    expect(seriesOf(option({ secondarySeries: [summary!] }), "history-dot:adaptive-score:svc")).toMatchObject({
      type: "scatter", data: [[START + 490, 0.349]] });
    // A result with no value has nothing to mark.
    expect(seriesOf(option({ secondarySeries: [score([observed(0, null)])] }), "history-dot:adaptive-score:svc")).toBeUndefined();
  });

  it("never invents a negative scale under non-negative values, and names the time once", () => {
    const built = option({ readings: [reading(), reading({ id: "reading:power", name: "Power" })] }, "monitoring");
    const axes = built.yAxis as Array<{ min: (extent: { min: number; max: number }) => number | null }>;
    expect(axes[0]!.min({ min: 0.02, max: 0.9 })).toBe(0);
    expect(axes[0]!.min({ min: 400, max: 410 })).toBeNull();
    expect(axes[0]!.min({ min: -3, max: 2 })).toBeNull();
    expect((built.xAxis as Array<{ axisPointer: { label: { show: boolean } } }>).map(axis => axis.axisPointer.label.show)).toEqual([false, true]);
    expect(built.tooltip).toMatchObject({ axisPointer: { type: "line" } });
  });

  it("leaves the padded ends of a score scale unlabelled", () => {
    const built = option({ secondarySeries: [score(steady(), { bounds: { minimum: 0.0927, maximum: 0.9992 } })] });
    const axis = (built.yAxis as Array<{ id: string; axisLabel: { formatter: (value: number) => string } }>)
      .find(item => item.id === "adaptive-score-values")!;
    expect([0.0927, 0.2, 0.9992].map(axis.axisLabel.formatter)).toEqual(["", "0.2", ""]);
  });

  it("names a series only where its line is drawn, and says which values are means or peaks", () => {
    const peak = { value: [START + 4900, 0.82], observation: observed(4900, 0.82, true), peak: { count: 15 } };
    const params = [
      { seriesId: "telemetry", seriesName: "Voltage", value: [START + 5000, 403.686636], axisValue: START + 5000 },
      { seriesId: "input::dev", seriesName: "dev", value: [START + 5000, 0.61437], axisValue: START + 5000 },
      { seriesId: "adaptive-score:svc", seriesName: "Anomaly score", value: peak.value, data: peak, axisValue: START + 5000 },
      { seriesId: "far", seriesName: "Stale", value: [START - 600_000, 1], axisValue: START + 5000 },
    ];
    const tooltip = formatTelemetryTooltip(params, "UTC", new Map([["Voltage", "V"]]), "en-US",
      new Map([["telemetry", 500], ["adaptive-score:svc", 5000], ["far", 500]]), new Set(["input::dev"]));
    expect(tooltip.split("\n").slice(1)).toEqual(["Voltage: 403.686636 V", "dev: 0.6144 (mean)",
      "Anomaly score: 0.82 (highest of 15)", "Alarm threshold: 0.6", "Alarm: active"]);
    // The exact-input tooltip of the Evidence tab steps aside: a peak is not the result under the pointer.
    expect(formatMonitoringObservationTooltip([{ seriesName: "Anomaly score", data: peak }], [reading()], String, String)).toBeUndefined();
  });
});
