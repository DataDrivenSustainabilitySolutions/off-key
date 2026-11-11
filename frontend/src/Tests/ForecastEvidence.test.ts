// @vitest-environment node
import { describe, expect, it } from "vitest";
import { buildForecastEvidence, formatForecastValue, intervalStatus } from "@/features/charts/forecast-evidence";
import { buildForecastChartSeries, formatForecastTooltip } from "@/features/charts/forecast-chart";
import { buildServiceHistoryModel } from "@/features/monitoring/historyModel";
import { buildMonitoringChartOption } from "@/features/charts/telemetry-chart";
import { historyPresentation } from "@/features/monitoring/historyPresentation";
import { futureForecastPoints, nextForecastView } from "@/features/charts/forecast-future";
import type { MonitoringForecast, MonitoringIssuedForecast } from "@/types/monitoring";
import type { MonitoringInput } from "@/domain/monitoring/serviceModel";
import type { PipelineServiceView } from "@/types/pipelines.generated";
import { chartEvidence } from "./support/fixtures/monitoring";

const start = Date.parse("2026-11-11T12:00:00Z");
const at = (seconds: number) => new Date(start + seconds * 1000).toISOString();
const forecast = (changes: Partial<MonitoringForecast> = {}): MonitoringForecast => ({
  detector_id: "timestral", target: "frequency", slot: "input_1", lead: 1, expected: 50, lower: 49.9, upper: 50.1, ...changes,
});
const row = (seconds: number, forecasts = [forecast()], observed: number | null = 50.2) => chartEvidence({
  monitor_id: "monitor", timestamp: at(seconds), sequence_number: seconds + 1, strategy: "adaptive_stream", anomaly_score: 2,
  reading_ids: ["reading"], input_timestamps: { reading: at(seconds - 0.075) }, forecasts,
  detector_inputs: [{ detector_id: null, inputs: { frequency: observed } }], threshold: 1.5, alarm: true,
});
const input: MonitoringInput = { stream: { id: "reading", label: "Frequency", broker_id: "broker", topic: "frequency",
  category: "Other", value_type: "number", unit: "Hz" }, binding: { policy: { mode: "original", interval_seconds: 1 } }, path: "Meter" };
const presentation = { bindings: { input_1: "reading" }, rawInputs: {}, intervalLabel: "NexCP interval" };
const colors = { foreground: "#111", mutedForeground: "#666", border: "#ddd", popover: "#fff", popoverForeground: "#111", muted: "#eee", primary: "#3a7e72" };
const issued = (origin = 0.925): MonitoringIssuedForecast => ({
  issued_at: at(origin + 0.2), origin_step: 20, origin_time: at(origin), time_basis: "estimated_cadence", step_seconds: 1,
  points: [1, 2, 3].map(lead => ({ lead, target_step: 20 + lead, target_time: at(origin + lead),
    expected: 50 + lead / 10, lower: 49.9, upper: 50.5 })),
});

describe("forecast evidence presentation", () => {
  it("overlays a raw forecast at its exact input timestamp and removes the repeated input", () => {
    const { model } = buildServiceHistoryModel({ serviceId: "monitor", inputs: [input], allInputs: [input], presentation,
      evidence: [row(1)], histories: new Map([["reading", [{ timestamp: at(0.925), value: 50.2 }]]]), dark: false });
    expect(model.detectorInputs).toEqual([]);
    expect(model.forecasts![0]!.data[0]!.value[0]).toBe(start + 925);
    expect(model.forecasts![0]!.name).toBe("Frequency (Hz) · 1 update ahead");
    const option = buildMonitoringChartOption({ model: { ...model, secondarySeries: [] }, colors, timeZone: "UTC",
      accessibleDescription: "Forecast", viewport: { mode: "live" }, layout: "monitoring" });
    expect(option.grid).toHaveLength(2);
    expect(option.series).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: `forecast:${model.forecasts![0]!.id}`, xAxisIndex: 0, yAxisIndex: 0 }),
      expect.objectContaining({ id: `residual:${model.forecasts![0]!.id}`, xAxisIndex: 1, yAxisIndex: 1 }),
    ]));
    expect(option.dataZoom).toMatchObject([{ xAxisIndex: [0, 1] }, { xAxisIndex: [0, 1] }]);
  });

  it("retains every lead and detector instead of taking the first forecast per feature", () => {
    const series = buildForecastEvidence([row(1, [forecast({ lead: 12 }), forecast(), forecast({ detector_id: "seasonal" })])], presentation.bindings);
    expect(series).toHaveLength(3);
    expect(series.map(line => line.lead)).toEqual([1, 1, 12]);
    expect(new Set(series.map(line => line.id)).size).toBe(3);
  });

  it("uses exact signed residuals and asymmetric calibrated bounds, including intervals crossing zero", () => {
    const [series] = buildForecastEvidence([row(1, [forecast({ lower: 49.7, upper: 50.1 })])], presentation.bindings);
    const options = buildForecastChartSeries(series!, 0, 1, "blue", "red");
    const residual = options.find(line => line.id === `residual:${series!.id}`)!;
    expect(residual.data).toEqual([expect.objectContaining({ value: [start + 925, expect.closeTo(0.2), expect.closeTo(-0.3), expect.closeTo(0.1)] })]);
    expect(residual.markPoint?.data).toHaveLength(1);
    expect(options.find(line => line.id === `forecast-band:residual:${series!.id}:width`)).toMatchObject({
      stackStrategy: "all", data: [[start + 925, expect.closeTo(0.4)]],
    });
  });

  it("keeps transformed or unassociated forecasts off the raw reading axis", () => {
    for (const [slot, bindings] of [[null, presentation.bindings], ["input_1", {}]] as const) {
      const { model } = buildServiceHistoryModel({ serviceId: "monitor", inputs: [input], allInputs: [input],
        presentation: { ...presentation, bindings }, evidence: [row(1, [forecast({ slot })])], histories: new Map(), dark: false });
      expect(model.forecasts![0]!.readingId).toBeUndefined();
      expect(model.detectorInputs).toHaveLength(1);
      const option = buildMonitoringChartOption({ model: { ...model, secondarySeries: [] }, colors, timeZone: "UTC",
        accessibleDescription: "Transformed", viewport: { mode: "live" }, layout: "monitoring" });
      expect(option.series).toEqual(expect.arrayContaining([expect.objectContaining({ id: `forecast:${model.forecasts![0]!.id}`, yAxisIndex: 1 })]));
    }
  });

  it("breaks missing and paused forecasts and never invents a band", () => {
    const series = buildForecastEvidence([row(0), row(1, [forecast({ lower: 51, upper: 49 })]), row(2, []), row(3), row(60)], presentation.bindings)[0]!;
    expect(series.data[1]!.value.slice(2)).toEqual([null, null]);
    expect(series.data.some(point => point.value[1] === null)).toBe(true);
    expect(series.data[series.data.length - 2]!.value[1]).toBeNull();
    const unbounded = buildForecastEvidence([row(1, [forecast({ lower: null, upper: null })], null)])[0]!;
    const options = buildForecastChartSeries(unbounded, 0, 1, "blue", "red");
    expect(options.some(line => String(line.id).startsWith("forecast-band:"))).toBe(false);
    expect(intervalStatus(unbounded.data[0]!.forecastObservation!)).toBe("Interval unavailable");
    expect(options[1]!.data).toEqual([expect.objectContaining({ value: [start + 1000, null, null, null] })]);
  });

  it("breaks a raw forecast when its exact input timestamp is missing", () => {
    const missing = { ...row(1), input_timestamps: {} };
    const series = buildForecastEvidence([row(0), missing, row(2)], presentation.bindings)[0]!;
    expect(series.data[1]!.value).toEqual([start + 1000, null, null, null]);
    expect(formatForecastValue(50.03125)).toBe("50.03125");
    expect(formatForecastValue(50.03135)).toBe("50.03135");
  });

  it("does not infer raw identity from names, values, or slot ordering", () => {
    const definition: PipelineServiceView["definition"] = { input_slots: [{ id: "input_1", label: "Frequency" }],
      nodes: [{ id: "timestral", kind: "detector", component: "detector:forecast.timestral" },
        { id: "calibration", kind: "calibration", component: "calibrate.nexcp" }], edges: [{ source: "features", target: "timestral" }] };
    const view: PipelineServiceView = { definition, history: [], layout: {},
      run: { id: "run", monitor_id: "monitor", revision_id: "revision", predecessor_run_id: null, status: "active", created_at: at(0), ended_at: null,
        execution: { definition, revision_id: "revision", run_id: "run", fingerprint: "test", bindings: [{ slot_id: "input_1", reading_id: "reading" }] } },
      validation: { valid: true, definition, features: { features: [{ name: "raw", raw: true, slots: ["input_1"] }, { name: "frequency", raw: false, slots: ["input_1"] }] } } };
    expect(historyPresentation(view)).toEqual({ bindings: { input_1: "reading" }, intervalLabel: "NexCP interval",
      rawInputs: { "input::raw": "reading", "input:timestral:raw": "reading" } });
  });

  it("names the interval and residual once and does not attach a neighbouring forecast to an unscored sample", () => {
    const series = buildForecastEvidence([row(1)], presentation.bindings)[0]!;
    const point = series.data[0]!;
    const entries = [
      { seriesId: `forecast:${series.id}`, seriesName: `${series.name} forecast`, value: point.value, data: point },
      { seriesId: `residual:${series.id}`, seriesName: `${series.name} residual`, value: point.value, data: structuredClone(point) },
    ];
    const tooltip = formatForecastTooltip(entries, String, value => value.toFixed(2), "NexCP interval")!;
    expect(tooltip.match(/NexCP interval/g)).toHaveLength(1);
    expect(tooltip).toContain("Residual: 0.20 · Outside interval");
    expect(formatForecastTooltip([{ value: [start + 1000, 51] }, ...entries], String, String, "NexCP interval")).toBeUndefined();
    expect(formatForecastTooltip([{ seriesId: "reading:reading", seriesName: "Frequency", value: [start + 1000, 51] }, ...entries], String, String, "NexCP interval"))
      .toContain("No evaluated forecast for this input sample.");
  });

  it("cycles overlay, ahead and data without altering residuals or underlying values", () => {
    const series = buildForecastEvidence([row(1, [forecast({ issued: issued(), lead: 3 })])], presentation.bindings)[0]!;
    series.future = futureForecastPoints(series.issued, start + 925, series.lead);
    expect(nextForecastView(nextForecastView(nextForecastView("overlay")))).toBe("overlay");
    const views = ["overlay", "ahead", "data"] as const;
    const charts = views.map(view => buildForecastChartSeries(series, 0, 1, "blue", "red", view));
    expect(charts.map(chart => chart.some(line => line.id === `forecast:${series.id}`))).toEqual([true, false, false]);
    expect(charts.map(chart => chart.some(line => line.id === `future:${series.id}`))).toEqual([true, true, false]);
    expect(charts.map(chart => chart.find(line => line.id === `residual:${series.id}`)?.data))
      .toEqual([charts[0]!.find(line => line.id === `residual:${series.id}`)!.data,
        charts[0]!.find(line => line.id === `residual:${series.id}`)!.data,
        charts[0]!.find(line => line.id === `residual:${series.id}`)!.data]);
    expect(buildForecastChartSeries(series, 0, -1, "blue", "red", "data")).toEqual([]);
    const future = charts[1]!.find(line => line.id === `future:${series.id}`)!;
    expect(future.data).toHaveLength(4); // Exact observed origin plus three real predictions.
    expect(future.markLine?.data).toHaveLength(2); // Origin boundary and the calibrated lead's interval.
    expect(charts[1]!.find(line => line.id === `future-bounds:${series.id}:upper`)?.data)
      .toEqual([[start + 1925, null], [start + 2925, null], [start + 3925, 50.5]]);
  });

  it("extends the shared time extent and never computes residuals for future values", () => {
    const { model } = buildServiceHistoryModel({ serviceId: "monitor", inputs: [input], allInputs: [input], presentation,
      evidence: [row(1, [forecast({ issued: issued(), lead: 3 })])],
      histories: new Map([["reading", [{ timestamp: at(0.925), value: 50.2 }]]]), dark: false });
    expect(model.extent?.[1]).toBe(start + 3925);
    const option = buildMonitoringChartOption({ model: { ...model, secondarySeries: [], forecastView: "ahead", showResiduals: false },
      colors, timeZone: "UTC", accessibleDescription: "Ahead", viewport: { mode: "live" }, layout: "monitoring" });
    expect(option.grid).toHaveLength(1);
    const series = model.forecasts![0]!;
    expect(buildForecastChartSeries(series, 0, 1, "blue", "red").find(line => line.id === `residual:${series.id}`)?.data)
      .toHaveLength(1);
  });

  it("uses only targets beyond observed history and does not reuse an old issuance after failure", () => {
    const make = (rows = [row(1, [forecast({ issued: issued(), lead: 3 })])], operational = true) => buildServiceHistoryModel({
      serviceId: "monitor", inputs: [input], allInputs: [input], presentation, operational, evidence: rows,
      histories: new Map([["reading", [{ timestamp: at(2.925), value: 50.4 }]]]), dark: false,
    }).model.forecasts![0]!;
    expect(make().future?.map(point => point.lead)).toEqual([3]);
    expect(make(undefined, false).future).toEqual([]);
    expect(make([row(1, [forecast({ issued: issued() })]), row(2)]).future).toEqual([]);
    expect(make([row(1, [forecast({ issued: issued() })]), row(2, [])]).future).toEqual([]);
    expect(futureForecastPoints({ ...issued(), time_basis: "unavailable" }, start + 925, 3)).toEqual([]);
    expect(futureForecastPoints({ ...issued(), origin_time: "invalid" }, start + 925, 3)).toEqual([]);
    expect(futureForecastPoints(undefined, start + 925, 3)).toEqual([]);
  });

  it("explains issue and estimated target times without claiming an observed outcome", () => {
    const point = futureForecastPoints(issued(), start + 925, 3)[2]!;
    const tooltip = formatForecastTooltip([{ seriesId: "future:signal", seriesName: "Frequency forecast ahead",
      value: [point.time, point.expected], data: { futureForecast: point } }], String, String, "NexCP interval")!;
    expect(tooltip).toContain("Estimated target:");
    expect(tooltip).toContain("NexCP interval at issue: 49.9 to 50.5");
    expect(tooltip).toContain("Outcome not yet observed");
    expect(tooltip).not.toMatch(/Residual:|Service alarm:/);
  });
});
