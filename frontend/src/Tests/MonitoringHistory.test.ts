// @vitest-environment node
import { describe, expect, it } from "vitest";
import { buildServiceHistoryModel } from "@/features/monitoring/historyModel";
import type { MonitoringInput } from "@/domain/monitoring/serviceModel";
import { buildMonitoringChartOption } from "@/features/charts/telemetry-chart";
import { formatMonitoringObservationTooltip } from "@/features/charts/monitoring-tooltip";
import { filterServiceAnomalies } from "@/lib/monitoring-chart";
import type { Anomaly } from "@/types/charger";
import type { MonitoringChartEvidence } from "@/types/monitoring";
import { trackerResult } from "./support/fixtures/monitoring";

const first = "2026-10-21T10:00:00.000Z";
const second = "2026-10-21T10:00:00.075Z";
const later = "2026-10-21T10:00:01.000Z";
const input = (id: string, unit: string): MonitoringInput => ({
  stream: { id, label: id, connection_id: "broker", topic: id, category: "Other", value_type: "number", unit },
  binding: { entity_id: "entity", telemetry_key: id, accepted_topic: id, policy: { mode: "original", interval_seconds: 1 } },
  path: "Room station",
});
const inputs = [input("temperature", "°C"), input("humidity", "%")];
const histories = new Map([
  ["temperature", [{ timestamp: first, value: 20 }, { timestamp: later, value: 999 }]],
  ["humidity", [{ timestamp: second, value: 55 }]],
]);
const row: MonitoringChartEvidence = {
  service_id: "forest", timestamp: second, created: later, sequence_number: 101,
  sensor_set: ["temperature", "humidity"], input_timestamps: { temperature: first, humidity: second },
  strategy: "adaptive_stream", model_type: "aberrant_online_isolation_forest",
  anomaly_score: 0.61, threshold: 0.6, alarm: true, restarted_martingale: null,
};
const build = (evidence: MonitoringChartEvidence[] = [row], visible = inputs) => buildServiceHistoryModel({
  serviceId: "forest", inputs: visible, allInputs: inputs, histories, evidence, dark: false,
});
const colors = { foreground: "#111", mutedForeground: "#666", border: "#ddd", popover: "#fff",
  popoverForeground: "#111", muted: "#eee", primary: "#3a7e72" };

describe("joint monitoring history", () => {
  it("plots a single raw forest result at its observation time with independently scaled input tracks", () => {
    const { model } = build();
    expect(model.readings.map(reading => reading.unit)).toEqual(["°C", "%"]);
    expect(model.secondarySeries).toHaveLength(1);
    expect(model.secondarySeries[0]!.name).toBe("Joint anomaly score");
    expect(model.secondarySeries[0]!.data.map(point => point.value)).toEqual([[Date.parse(second), 0.61]]);
    expect(model.readings.map(reading => reading.alarmTimes)).toEqual([[Date.parse(first)], [Date.parse(second)]]);
    const option = buildMonitoringChartOption({ model, colors, timeZone: "UTC", accessibleDescription: "Joint forest", layout: "monitoring", viewport: { mode: "live" } });
    expect(option.grid).toHaveLength(3);
    expect(option.axisPointer).toMatchObject({ link: [{ xAxisIndex: "all" }] });
    expect(option.dataZoom).toMatchObject([{ xAxisIndex: [0, 1, 2] }, { xAxisIndex: [0, 1, 2] }]);
    expect(option.series).toEqual(expect.arrayContaining([expect.objectContaining({ id: "threshold:adaptive-score:forest", lineStyle: expect.objectContaining({ type: "dashed" }) })]));
  });

  it("retains the joint score and full input identity when a reading is hidden", () => {
    const all = build().model;
    const selected = build([row], [inputs[0]!]).model;
    expect(selected.readings).toHaveLength(1);
    expect(selected.secondarySeries).toEqual(all.secondarySeries);
    expect(selected.secondarySeries[0]!.latestObservation.inputTimestamps).toEqual(row.input_timestamps);
  });

  it("uses the exact historical input in hover rather than a nearby later reading", () => {
    const { model } = build();
    const text = formatMonitoringObservationTooltip([{ seriesName: "Joint anomaly score", data: model.secondarySeries[0]!.data[0] }],
      model.readings, time => new Date(time).toISOString(), String);
    expect(text).toContain("temperature: 20 °C");
    expect(text).toContain("humidity: 55 %");
    expect(text).not.toContain("999");
    expect(text).toContain(`Input time: ${first}`);
    expect(text).toContain("(-75 ms)");
    expect(text).toContain("Joint result across 2 inputs");
    expect(text).toContain("Alarm: active");
  });

  it("preserves scored observations when their input history is unavailable", () => {
    const { model } = buildServiceHistoryModel({ serviceId: "forest", inputs, allInputs: inputs, histories: new Map(), evidence: [row], dark: false });
    expect(model.readings.every(reading => reading.data.length === 0)).toBe(true);
    expect(model.secondarySeries[0]!.latestObservation.value).toBe(0.61);
    const text = formatMonitoringObservationTooltip([{ seriesName: "Joint anomaly score", data: model.secondarySeries[0]!.data[0] }], model.readings, String, String);
    expect(text).toContain("temperature: input not loaded");
    expect(text).toContain("humidity: input not loaded");
    expect(text).not.toContain("temperature: 0");
  });

  it("does not associate a new unscored reading with a nearby old score in hover", () => {
    const { model } = build();
    const text = formatMonitoringObservationTooltip([
      { seriesName: "temperature", value: [Date.parse(later), 999] },
      { seriesName: "Joint anomaly score", data: model.secondarySeries[0]!.data[0] },
    ], model.readings, time => new Date(time).toISOString(), String);
    expect(text).toContain("temperature: 999 °C");
    expect(text).toContain("No evaluated result for this input sample");
    expect(text).not.toContain("Joint anomaly score: 0.61");
  });

  it("matches a scored sensor by stable series identity when display names repeat", () => {
    const { model } = build();
    const readings = model.readings.map(reading => ({ ...reading, name: "Same name" }));
    const text = formatMonitoringObservationTooltip([
      { seriesId: "reading:humidity", seriesName: "Same name", value: [Date.parse(second), 55] },
      { seriesName: "Joint anomaly score", data: model.secondarySeries[0]!.data[0] },
    ], readings, String, String);
    expect(text).toContain("Joint anomaly score: 0.61");
    expect(text).not.toContain("No evaluated result");
  });

  it("does not attach old results to a hovered pending-score marker", () => {
    const { model } = build();
    const text = formatMonitoringObservationTooltip([
      { seriesId: "pending-reading:temperature", seriesName: "Awaiting anomaly score", value: [Date.parse(later), 999] },
      { seriesName: "Joint anomaly score", data: model.secondarySeries[0]!.data[0] },
    ], model.readings, String, String);
    expect(text).toContain("No evaluated result for this input sample");
    expect(text).not.toContain("Joint anomaly score: 0.61");
  });

  it("keeps inputs usable without detector evidence and excludes another service's decisions", () => {
    const { model } = build([{ ...row, service_id: "retired", anomaly_score: 100 }]);
    expect(model.readings[0]!.data).toHaveLength(2);
    expect(model.secondarySeries).toEqual([]);
    expect(model.readings.every(reading => reading.alarmTimes!.length === 0)).toBe(true);
  });

  it("retains static logarithmic evidence and overflow alongside multiple readings", () => {
    const { model } = build([{ ...row, strategy: "static_baseline", anomaly_score: undefined,
      tracker_results: [trackerResult({ statistic_value: null, statistic_is_infinite: true, log_statistic_value: 1000,
        alarm_fired: true, alarm_active: true, alarm_count: 1 })],
    }]);
    expect(model.secondarySeries[0]!.overflow).toHaveLength(1);
    const option = buildMonitoringChartOption({ model, colors, timeZone: "UTC", accessibleDescription: "Joint static", layout: "monitoring", viewport: { mode: "live" } });
    expect(option.yAxis).toEqual(expect.arrayContaining([expect.objectContaining({ type: "log", gridIndex: 2 })]));
  });

  it("scopes reading alarm markers to the same service as its scores, including legacy associations", () => {
    const anomaly = (id: string, serviceId: string | null, timestamp = second): Anomaly => ({ anomaly_id: id, service_id: serviceId,
      charger_id: "entity", timestamp, telemetry_type: "temperature", anomaly_type: "adaptive", anomaly_value: 0.61, value_type: null });
    const anomalies = [anomaly("current", "forest"), anomaly("retired", "retired"), anomaly("legacy", null), anomaly("unmatched", null, later)];
    expect(filterServiceAnomalies(anomalies, [row], "forest", "temperature").map(item => item.anomaly_id)).toEqual(["current", "legacy"]);
    expect(filterServiceAnomalies(anomalies, [row], undefined, "temperature")).toEqual(anomalies);
  });
});
