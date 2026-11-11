// @vitest-environment node
import { describe, expect, it } from "vitest";
import { buildDetectorInputSeries, MAX_DETECTOR_INPUT_SERIES } from "@/features/charts/detector-inputs";
import { formatMonitoringObservationTooltip } from "@/features/charts/monitoring-tooltip";
import { buildMonitoringChartOption, buildTelemetryChartModel, buildTelemetryChartOption, formatTelemetryTooltip } from "@/features/charts/telemetry-chart";
import { collectTelemetryChartDetectors } from "@/features/charts/telemetry-detectors";
import { buildServiceHistoryModel } from "@/features/monitoring/historyModel";
import type { MonitoringInput } from "@/domain/monitoring/serviceModel";
import type { MonitoringChartEvidence, MonitoringDetectorInputs, MonitoringForecast } from "@/types/monitoring";
import { chartEvidence, trackerResult } from "./support/fixtures/monitoring";

const start = Date.parse("2026-11-03T08:00:00Z");
const at = (seconds: number) => new Date(start + seconds * 1000).toISOString();
const row = (seconds: number, inputs: MonitoringDetectorInputs[] | undefined, sequence = seconds): MonitoringChartEvidence =>
  chartEvidence({ monitor_id: "phases", timestamp: at(seconds), sequence_number: sequence, reading_ids: ["L1"],
    strategy: "static_baseline", tracker_results: [trackerResult()], detector_inputs: inputs });
const flat = (l1: number | null, l2: number | null): MonitoringDetectorInputs[] =>
  [{ detector_id: null, inputs: { L1_dev: l1, L2_dev: l2 } }];
const time = (row: MonitoringChartEvidence) => Date.parse(row.timestamp);
const colors = { foreground: "#111", mutedForeground: "#666", border: "#ddd", popover: "#fff",
  popoverForeground: "#111", muted: "#eee", primary: "#3a7e72" };

describe("detector inputs", () => {
  it("draws one line per scored feature at each evaluated observation", () => {
    const series = buildDetectorInputSeries([row(2, flat(0.02, -0.01)), row(1, flat(0.01, -0.02))], time);
    expect(series.map(line => line.name)).toEqual(["L1_dev", "L2_dev"]);
    expect(series[0]!.data).toEqual([[start + 1000, 0.01], [start + 2000, 0.02]]);
    expect(series[1]!.data).toEqual([[start + 1000, -0.02], [start + 2000, -0.01]]);
  });

  it("names each combined detector's features and skips rows written before inputs were stored", () => {
    const fused: MonitoringDetectorInputs[] = [
      { detector_id: "pca", inputs: { L1_dev: 0.01 } }, { detector_id: "forest", inputs: { L1_dev: 0.03 } }];
    const series = buildDetectorInputSeries([row(0, undefined), row(1, []), row(2, fused)], time);
    expect(series.map(line => line.name)).toEqual(["pca · L1_dev", "forest · L1_dev"]);
    expect(series.map(line => line.data)).toEqual([[[start + 2000, 0.01]], [[start + 2000, 0.03]]]);
  });

  it("breaks the lines across a pause, such as one a Gate holds back, and where a value is missing", () => {
    const rows = [0, 1, 2, 3, 60, 61].map(seconds => row(seconds, flat(seconds === 2 ? null : seconds, 0)));
    const [l1] = buildDetectorInputSeries(rows, time);
    expect(l1!.data).toEqual([
      [start, 0], [start + 1000, 1], [start + 2000, null], [start + 3000, 3],
      [start + 31500, null], [start + 60000, 60], [start + 61000, 61],
    ]);
  });

  it("keeps the chart's window, drops features that never had a value and caps the number of lines", () => {
    const many = Object.fromEntries(Array.from({ length: MAX_DETECTOR_INPUT_SERIES + 3 }, (_, index) => [`f${index}`, index]));
    const rows = [row(0, [{ detector_id: null, inputs: { ...many, empty: null } }]), row(10, flat(1, 1))];
    const series = buildDetectorInputSeries(rows, time, [start - 1000, start + 1000]);
    expect(series).toHaveLength(MAX_DETECTOR_INPUT_SERIES);
    expect(series.every(line => line.data.length === 1)).toBe(true);
    expect(series.map(line => line.name)).not.toContain("empty");
  });

  it("adds a pane between the reading and the evidence, with its own axis, lines and legend", () => {
    const rows = [row(0, flat(0.01, -0.01)), row(1, flat(0.02, -0.02))];
    const telemetry: Array<[number, number]> = [[start, 10], [start + 1000, 11]];
    const detectors = collectTelemetryChartDetectors({ telemetryType: "L1", evidence: rows, telemetryTimes: telemetry.map(([t]) => t) });
    const model = buildTelemetryChartModel({ telemetryName: "AC2", telemetryColor: "#2563eb", telemetry, detectors,
      anomalyMarkers: [], detectorInputs: buildDetectorInputSeries(rows, time) });
    const options = { model, colors, timeZone: "UTC", accessibleDescription: "Phases", viewport: { mode: "live" } as const };
    const standard = buildTelemetryChartOption(options);
    expect(standard.grid).toHaveLength(3);
    expect(standard.yAxis).toEqual([
      expect.objectContaining({ gridIndex: 0 }),
      expect.objectContaining({ id: "detector-input-values", gridIndex: 1, name: "Detector inputs" }),
      expect.objectContaining({ type: "log", gridIndex: 2 }),
    ]);
    const lines = (standard.series as Array<{ id?: string; xAxisIndex?: number; yAxisIndex?: number }>)
      .filter(series => series.id?.startsWith("input:"));
    expect(lines).toEqual([
      expect.objectContaining({ id: "input::L1_dev", xAxisIndex: 1, yAxisIndex: 1 }),
      expect.objectContaining({ id: "input::L2_dev", xAxisIndex: 1, yAxisIndex: 1 }),
    ]);
    const compact = buildTelemetryChartOption({ ...options, layout: "compact" });
    expect(compact.legend).toMatchObject({ id: "detector-inputs-legend", data: ["L1_dev", "L2_dev"] });
  });

  it("leaves the chart unchanged when no observation stored its inputs", () => {
    const telemetry: Array<[number, number]> = [[start, 10]];
    const model = buildTelemetryChartModel({ telemetryName: "AC2", telemetryColor: "#2563eb", telemetry, detectors: [],
      anomalyMarkers: [], detectorInputs: buildDetectorInputSeries([row(0, [])], time) });
    const option = buildTelemetryChartOption({ model, colors, timeZone: "UTC", accessibleDescription: "Phases", viewport: { mode: "live" } });
    expect(option.grid).toHaveLength(1);
    expect(option.legend).toMatchObject({ id: "telemetry-legend" });
  });

  it("shows the service's inputs in its history and names them in the hover", () => {
    const input: MonitoringInput = {
      stream: { id: "L1", label: "AC1", broker_id: "broker", topic: "L1", category: "Other", value_type: "number", unit: "A" },
      binding: { policy: { mode: "original", interval_seconds: 1 } },
      path: "Charger 07",
    };
    const rows = [row(0, flat(0.01, -0.01)), row(1, flat(0.02, -0.02))];
    const { model } = buildServiceHistoryModel({ serviceId: "phases", inputs: [input], allInputs: [input],
      histories: new Map([["L1", [{ timestamp: at(0), value: 10 }, { timestamp: at(1), value: 11 }]]]), evidence: rows, dark: false });
    expect(model.detectorInputs?.map(line => line.name)).toEqual(["L1_dev", "L2_dev"]);
    const option = buildMonitoringChartOption({ model, colors, timeZone: "UTC", accessibleDescription: "Phases",
      layout: "monitoring", viewport: { mode: "live" } });
    expect(option.grid).toHaveLength(3);
    const text = formatMonitoringObservationTooltip([
      { seriesId: "input::L1_dev", seriesName: "L1_dev", value: [start + 1000, 0.02] },
      { seriesId: "input::L2_dev", seriesName: "L2_dev", value: [start + 1000, -0.02] },
      { seriesName: "Restarted e-process", data: model.secondarySeries[0]!.data[1] },
    ], model.readings, String, String);
    expect(text).toContain("L1_dev: 0.02");
    expect(text).toContain("L2_dev: -0.02");
  });
});

describe("forecasts of a forecaster step", () => {
  const load = (value: number): MonitoringDetectorInputs[] => [{ detector_id: null, inputs: { load: value } }];
  const expected = (value: number, lower: number | null = null, upper: number | null = null): MonitoringForecast =>
    ({ detector_id: "timestral", target: "load", slot: null, lead: 1, expected: value, lower, upper });
  const forecast = (seconds: number, value: number, forecasts: MonitoringForecast[] = []) =>
    ({ ...row(seconds, load(value)), forecasts });

  it("puts each forecast on the line of the feature it was made for", () => {
    const rows = [forecast(0, 10), forecast(1, 11, [expected(10.5, 9.5, 11.5)]), forecast(2, 12, [expected(11.5, 10.5, 12.5)])];
    const [line] = buildDetectorInputSeries(rows, time);
    expect(line!.data).toEqual([[start, 10], [start + 1000, 11], [start + 2000, 12]]);
    // The first observation had no forecast yet, so the forecast starts at the second.
    expect(line!.forecast).toEqual([[start + 1000, 10.5, 9.5, 11.5], [start + 2000, 11.5, 10.5, 12.5]]);
  });

  it("finds the line by detector when several score the same feature, and skips what it cannot place", () => {
    const inputs: MonitoringDetectorInputs[] = [
      { detector_id: "timestral", inputs: { load: 10 } }, { detector_id: "forest", inputs: { load: 10 } }];
    const rows = [{ ...row(0, inputs), forecasts: [expected(9), { ...expected(3), target: "other" },
      { ...expected(Number.NaN), detector_id: "forest" }] }];
    const [timestral, forest] = buildDetectorInputSeries(rows, time);
    expect(timestral!.forecast).toEqual([[start, 9, null, null]]);
    expect(forest!.forecast).toBeUndefined();
  });

  it("keeps a forecast without an interval, drops bounds that are not an interval and breaks where one is missing", () => {
    const rows = [forecast(0, 10, [expected(10)]), forecast(1, 10, [expected(10, 12, 8)]), forecast(2, 10),
      forecast(3, 10, [expected(10, 9, 11)]), forecast(60, 10, [expected(10, 9, 11)])];
    const [line] = buildDetectorInputSeries(rows, time);
    expect(line!.forecast).toEqual([
      [start, 10, null, null], [start + 1000, 10, null, null], [start + 2000, null, null, null],
      [start + 3000, 10, 9, 11], [start + 31500, null, null, null], [start + 60000, 10, 9, 11],
    ]);
  });

  it("draws the forecast dashed in the feature's pane and the interval as a band between its bounds", () => {
    const rows = [forecast(0, -1, [expected(-0.5, -2, 1)]), forecast(1, 0, [expected(0.5, -1, 2)])];
    const telemetry: Array<[number, number]> = [[start, 10], [start + 1000, 11]];
    const model = buildTelemetryChartModel({ telemetryName: "Load", telemetryColor: "#2563eb", telemetry, detectors: [],
      anomalyMarkers: [], detectorInputs: buildDetectorInputSeries(rows, time) });
    const option = buildTelemetryChartOption({ model, colors, timeZone: "UTC", accessibleDescription: "Load", viewport: { mode: "live" } });
    const series = (option.series as Array<{ id?: string }>).filter(item => item.id?.startsWith("forecast"));
    expect(series).toEqual([
      expect.objectContaining({ id: "forecast::load", name: "load forecast", xAxisIndex: 1, yAxisIndex: 1,
        lineStyle: expect.objectContaining({ type: "dashed" }), data: [[start, -0.5, -2, 1], [start + 1000, 0.5, -1, 2]] }),
      // The lower bound and the width above it are stacked, so the fill starts at the lower bound.
      expect.objectContaining({ id: "forecast-band::load:lower", stack: "forecast-band::load", stackStrategy: "all",
        data: [[start, -2], [start + 1000, -1]] }),
      expect.objectContaining({ id: "forecast-band::load:width", stack: "forecast-band::load", stackStrategy: "all",
        areaStyle: expect.objectContaining({ opacity: 0.15 }), data: [[start, 3], [start + 1000, 3]] }),
    ]);
    expect((series[1] as { areaStyle?: unknown }).areaStyle).toBeUndefined();
  });

  it("draws no band for a step without an interval", () => {
    const rows = [forecast(0, 10, [expected(10)]), forecast(1, 11, [expected(10.5)])];
    const model = buildTelemetryChartModel({ telemetryName: "Load", telemetryColor: "#2563eb", telemetry: [[start, 10]], detectors: [],
      anomalyMarkers: [], detectorInputs: buildDetectorInputSeries(rows, time) });
    const option = buildTelemetryChartOption({ model, colors, timeZone: "UTC", accessibleDescription: "Load", viewport: { mode: "live" } });
    expect((option.series as Array<{ id?: string }>).map(item => item.id).filter(id => id?.startsWith("forecast")))
      .toEqual(["forecast::load"]);
  });

  it("names the forecast and its interval once in the hover", () => {
    const hovered = [
      { seriesId: "input::load", seriesName: "load", value: [start, 11] },
      { seriesId: "forecast::load", seriesName: "load forecast", value: [start, 10.5, 9.5, 11.5] },
      { seriesId: "forecast-band::load:lower", seriesName: "series\u00003", value: [start, 9.5] },
      { seriesId: "forecast-band::load:width", seriesName: "series\u00004", value: [start, 2] },
    ];
    expect(formatTelemetryTooltip(hovered, "UTC", new Map(), "en-US").split("\n").slice(1))
      .toEqual(["load: 11", "load forecast: 10.5 (9.5 to 11.5)"]);
    expect(formatTelemetryTooltip([{ ...hovered[1], value: [start, 10.5, null, null] }], "UTC", new Map(), "en-US"))
      .toContain("load forecast: 10.5");
    // A service's history names the same in the hover of an evaluated observation.
    const input: MonitoringInput = {
      stream: { id: "L1", label: "Load", broker_id: "broker", topic: "L1", category: "Other", value_type: "number", unit: "kW" },
      binding: { policy: { mode: "original", interval_seconds: 1 } },
      path: "Charger 07",
    };
    const { model } = buildServiceHistoryModel({ serviceId: "phases", inputs: [input], allInputs: [input],
      histories: new Map([["L1", [{ timestamp: at(0), value: 11 }]]]),
      evidence: [forecast(0, 11, [expected(10.5, 9.5, 11.5)])], dark: false });
    const text = formatMonitoringObservationTooltip(
      [...hovered, { seriesName: "Restarted e-process", data: model.secondarySeries[0]!.data[0] }], model.readings, String, String);
    expect(text?.split("\n").filter(line => line.startsWith("load"))).toEqual(["load: 11", "load forecast: 10.5 (9.5 to 11.5)"]);
  });
});
