import { describe, expect, it } from "vitest";

import { createAnomalyMarkers, MULTIVARIATE_TELEMETRY_TYPE } from "@/lib/anomaly-utils";
import {
  buildTelemetryEventMarkPoints,
  formatEventSampleOffset,
  formatTelemetryEventTooltip,
  groupTelemetryEvents,
} from "@/lib/telemetry-events";
import type { Anomaly } from "@/types/charger";

const anomaly: Anomaly = {
  anomaly_id: "event-a",
  charger_id: "test-charger",
  timestamp: "2026-05-19T08:00:00.000Z",
  telemetry_type: "L1",
  anomaly_type: "threshold_exceeded",
  anomaly_value: 0.004,
  value_type: "tail_pvalue",
  sensor_set: ["L1"],
};
const time = Date.parse(anomaly.timestamp);
const options = {
  timeZone: "UTC",
  locale: "en-GB",
  unit: "V",
  colors: { foreground: "#111", mutedForeground: "#666", popover: "#fff" },
};

describe("telemetry event presentation", () => {
  it("groups coincident distinct events without changing their recorded time", () => {
    const markers = createAnomalyMarkers([], [
      { ...anomaly, anomaly_id: "later", timestamp: "2026-05-19T08:00:02.000Z" },
      anomaly,
      { ...anomaly, anomaly_id: "event-b", anomaly_type: "spike" },
    ]);
    const groups = groupTelemetryEvents(markers);

    expect(groups).toHaveLength(2);
    expect(groups[0]?.timeMs).toBe(time);
    expect(groups[0]?.events.map(({ anomaly: event }) => event.anomaly_id)).toEqual(["event-a", "event-b"]);
    expect(groups[1]?.timeMs).toBe(time + 2_000);
  });

  it("renders a matched circle at event time with the nearest sample value", () => {
    const groups = groupTelemetryEvents(createAnomalyMarkers([
      { timestamp: "2026-05-19T08:00:03.000Z", value: 230 },
    ], [anomaly]));
    const marks = buildTelemetryEventMarkPoints(groups, options);

    expect(marks[0]).toMatchObject({ coord: [time, 230], symbol: "circle" });
    expect(marks[0]?.y).toBeUndefined();
    const tooltip = marks[0]?.tooltip.formatter();
    expect(tooltip).toContain("Anomaly recorded at:");
    expect(tooltip).toContain("08:00:00.000 UTC");
    expect(tooltip).toContain("Nearest telemetry sample at:");
    expect(tooltip).toContain("08:00:03.000 UTC");
    expect(tooltip).toContain("Telemetry value: 230 V");
    expect(tooltip).toContain("Sample offset: +3 s (sample after event)");
  });

  it("renders unmatched events as top-edge triangles instead of inventing a telemetry value", () => {
    const groups = groupTelemetryEvents(createAnomalyMarkers([], [anomaly]));
    const marks = buildTelemetryEventMarkPoints(groups, options);

    expect(marks[0]).toMatchObject({
      coord: [time, 0],
      relativeTo: "coordinate",
      y: "0%",
      symbol: "triangle",
      symbolRotate: 180,
      symbolOffset: [0, 6],
    });
    expect(marks[0]?.tooltip.formatter()).toContain("No nearby telemetry sample.");
    expect(marks[0]?.tooltip.formatter()).not.toContain("Telemetry value:");
  });

  it.each([
    ["above", 1_000, "0%", 6],
    ["below", 10, "100%", -6],
  ] as const)("keeps matched circles visible when their contextual sample is %s the telemetry range", (direction, value, y, inset) => {
    const sampleTimestamp = "2026-05-19T08:00:03.000Z";
    const groups = groupTelemetryEvents(createAnomalyMarkers([
      { timestamp: sampleTimestamp, value },
    ], [anomaly, { ...anomaly, anomaly_id: "event-b" }]));
    const marks = buildTelemetryEventMarkPoints(groups, {
      ...options,
      extent: [time, time + 1_000],
      telemetryValueExtent: [200, 250],
    });

    expect(marks).toHaveLength(1);
    expect(marks[0]).toMatchObject({
      coord: [time, value],
      symbol: "circle",
      relativeTo: "coordinate",
      y,
      symbolOffset: [0, inset],
      label: { show: true, formatter: "2" },
    });
    const tooltip = marks[0]?.tooltip.formatter();
    expect(tooltip).toContain(`Contextual sample is ${direction} the displayed telemetry range.`);
    expect(tooltip).toContain(`Telemetry value: ${value === 1_000 ? "1,000" : "10"} V`);
    expect(tooltip).toContain("Nearest telemetry sample at:");
    expect(tooltip).toContain("08:00:03.000 UTC");
    expect(tooltip).toContain("Sample offset: +3 s (sample after event)");
    expect(tooltip).toContain("Event event-a:");
    expect(tooltip).toContain("Event event-b:");
  });

  it.each([200, 225, 250])("keeps an in-range or boundary sample at its actual plotted value %s", (value) => {
    const groups = groupTelemetryEvents(createAnomalyMarkers([
      { timestamp: anomaly.timestamp, value },
    ], [anomaly]));
    const marks = buildTelemetryEventMarkPoints(groups, { ...options, telemetryValueExtent: [200, 250] });

    expect(marks[0]).toMatchObject({ coord: [time, value], symbol: "circle" });
    expect(marks[0]?.y).toBeUndefined();
    expect(marks[0]?.relativeTo).toBeUndefined();
    expect(marks[0]?.symbolOffset).toBeUndefined();
    expect(marks[0]?.tooltip.formatter()).not.toContain("displayed telemetry range");
  });

  it("does not clamp contextual markers against invalid value extents", () => {
    const groups = groupTelemetryEvents(createAnomalyMarkers([
      { timestamp: anomaly.timestamp, value: 230 },
    ], [anomaly]));
    for (const telemetryValueExtent of [[Number.NaN, 250], [200, Number.POSITIVE_INFINITY], [250, 200]] as const) {
      const marks = buildTelemetryEventMarkPoints(groups, { ...options, telemetryValueExtent });
      expect(marks[0]?.y).toBeUndefined();
      expect(marks[0]?.tooltip.formatter()).not.toContain("displayed telemetry range");
    }
  });

  it("filters both matched and unmatched events to the inclusive displayed timeline", () => {
    const markers = createAnomalyMarkers([
      { timestamp: anomaly.timestamp, value: 1 },
    ], [
      { ...anomaly, anomaly_id: "before", timestamp: "2026-05-19T07:59:59.999Z" },
      anomaly,
      { ...anomaly, anomaly_id: "end", timestamp: "2026-05-19T08:01:00.000Z" },
      { ...anomaly, anomaly_id: "after", timestamp: "2026-05-19T08:01:00.001Z" },
    ]);
    const marks = buildTelemetryEventMarkPoints(groupTelemetryEvents(markers), {
      ...options,
      extent: [time, time + 60_000],
    });

    expect(marks.map(({ coord }) => coord?.[0])).toEqual([time, time + 60_000]);
    expect(marks.map(({ symbol }) => symbol)).toEqual(["circle", "triangle"]);
  });

  it("labels coincident event counts and lists every event in the tooltip", () => {
    const groups = groupTelemetryEvents(createAnomalyMarkers([], [
      anomaly,
      { ...anomaly, anomaly_id: "event-b", anomaly_type: "spike" },
    ]));
    const marks = buildTelemetryEventMarkPoints(groups, options);

    expect(marks).toHaveLength(1);
    expect(marks[0]?.label).toMatchObject({ show: true, formatter: "2" });
    expect(marks[0]?.tooltip.formatter()).toContain("2 anomaly events");
    expect(marks[0]?.tooltip.formatter()).toContain("Event event-a:");
    expect(marks[0]?.tooltip.formatter()).toContain("Event event-b:");
  });

  it("describes multivariate sample values as nearby context", () => {
    const groups = groupTelemetryEvents(createAnomalyMarkers([
      { timestamp: anomaly.timestamp, value: 230 },
    ], [{ ...anomaly, telemetry_type: MULTIVARIATE_TELEMETRY_TYPE, sensor_set: ["L1", "L2"] }]));
    const tooltip = formatTelemetryEventTooltip(groups[0]!, options);

    expect(tooltip).toContain("Sensors: L1, L2");
    expect(tooltip).toContain("exact detector input is not recorded with the event");
  });

  it("formats signed subsecond offsets without dropping the event/sample distinction", () => {
    expect(formatEventSampleOffset(-125)).toBe("−125 ms (sample before event)");
    expect(formatEventSampleOffset(125)).toBe("+125 ms (sample after event)");
    expect(formatEventSampleOffset(0)).toBe("0 ms (same timestamp)");
  });
});
