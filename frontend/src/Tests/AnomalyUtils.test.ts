import { describe, expect, it } from "vitest";

import {
  createAnomalyZones,
  createAnomalyMarkers,
  filterAnomalies,
  hasAnomaly,
  MULTIVARIATE_TELEMETRY_TYPE,
  getAnomalyStyle,
} from "../lib/anomaly-utils";
import { findNearestTelemetryPoint } from "../lib/time-utils";
import type { Anomaly } from "../types/charger";

const baseAnomaly: Anomaly = {
  anomaly_id: "anomaly-1",
  charger_id: "charger-1",
  timestamp: "2026-05-19T08:00:00.000Z",
  telemetry_type: "L1",
  anomaly_type: "ml_tailprob_univariate",
  anomaly_value: 0.004,
  value_type: "tail_pvalue",
};

describe("anomaly chart utilities", () => {
  it("includes multivariate anomalies only on involved telemetry charts", () => {
    const anomalies: Anomaly[] = [
      baseAnomaly,
      {
        ...baseAnomaly,
        anomaly_id: "anomaly-2",
        telemetry_type: MULTIVARIATE_TELEMETRY_TYPE,
        anomaly_type: "ml_conformal_static_multivariate",
        value_type: "conformal_pvalue",
        sensor_set: ["L1", "L2"],
      },
    ];

    const l1Filtered = filterAnomalies(anomalies, "L1");
    const l3Filtered = filterAnomalies(anomalies, "L3");

    expect(l1Filtered.map((anomaly) => anomaly.anomaly_id)).toEqual([
      "anomaly-1",
      "anomaly-2",
    ]);
    expect(l3Filtered).toHaveLength(0);
  });

  it("keeps legacy multivariate anomalies visible when no sensor set exists", () => {
    const anomalies: Anomaly[] = [
      {
        ...baseAnomaly,
        anomaly_id: "anomaly-legacy",
        telemetry_type: MULTIVARIATE_TELEMETRY_TYPE,
        anomaly_type: "ml_conformal_static_multivariate",
        value_type: "conformal_pvalue",
      },
    ];

    const filtered = filterAnomalies(anomalies, "L3");

    expect(filtered).toHaveLength(1);
  });

  it("returns configured style for known anomaly types and defaults otherwise", () => {
    expect(getAnomalyStyle("threshold_exceeded")).toEqual({
      color: "#ef4444",
      radius: 3,
      opacity: 0.8,
    });

    expect(getAnomalyStyle("does-not-exist")).toEqual({
      color: "#dc2626",
      radius: 3,
      opacity: 0.8,
    });
  });

  it("clusters nearby anomalies into zones with full anomaly payloads", () => {
    const anomalies: Anomaly[] = [
      {
        ...baseAnomaly,
        anomaly_id: "zone-a",
        telemetry_type: "L1",
        timestamp: "2026-05-19T08:00:00.000Z",
      },
      {
        ...baseAnomaly,
        anomaly_id: "zone-b",
        telemetry_type: "L2",
        timestamp: "2026-05-19T08:04:00.000Z",
        anomaly_type: "ml_conformal_static_multivariate",
        value_type: "conformal_pvalue",
      },
      {
        ...baseAnomaly,
        anomaly_id: "zone-c",
        telemetry_type: "L1",
        timestamp: "2026-05-19T09:00:00.000Z",
      },
    ];

    const zones = createAnomalyZones(anomalies);

    expect(zones).toHaveLength(2);
    expect(zones[0]?.anomalies.map((anomaly) => anomaly.anomaly_id)).toEqual([
      "zone-a",
      "zone-b",
    ]);
    expect(zones[1]?.anomalies.map((anomaly) => anomaly.anomaly_id)).toEqual(["zone-c"]);
  });

  it("sorts anomalies by timestamp before clustering", () => {
    const zones = createAnomalyZones([
      { ...baseAnomaly, anomaly_id: "late", timestamp: "2026-05-19T09:00:00.000Z" },
      { ...baseAnomaly, anomaly_id: "early", timestamp: "2026-05-19T08:00:00.000Z" },
      { ...baseAnomaly, anomaly_id: "mid", timestamp: "2026-05-19T08:04:00.000Z" },
    ]);

    expect(zones).toHaveLength(2);
    expect(zones[0]?.anomalies.map((anomaly) => anomaly.anomaly_id)).toEqual([
      "early",
      "mid",
    ]);
    expect(zones[1]?.anomalies.map((anomaly) => anomaly.anomaly_id)).toEqual(["late"]);
  });

  it("ignores invalid timestamps when creating anomaly zones", () => {
    const zones = createAnomalyZones([
      { ...baseAnomaly, anomaly_id: "bad", timestamp: "not-a-date" },
      { ...baseAnomaly, anomaly_id: "zone-a", timestamp: "2026-05-19T08:00:00.000Z" },
    ]);
    expect(zones).toHaveLength(1);
    expect(zones[0]?.anomalies.map((anomaly) => anomaly.anomaly_id)).toEqual([
      "zone-a",
    ]);
  });

  it("accepts valid timezone-offset timestamps when creating zones", () => {
    const timestamp = "2026-05-19T08:00:00+01:00";
    const zones = createAnomalyZones([
      {
        ...baseAnomaly,
        anomaly_id: "offset",
        timestamp,
      },
    ]);
    expect(zones).toHaveLength(1);
    const timestampMs = Date.parse(timestamp);
    expect(zones[0]).toMatchObject({ startMs: timestampMs, endMs: timestampMs });
    expect(zones[0]?.anomalies[0]?.anomaly_id).toBe("offset");
  });

  it("returns no zones when all anomaly timestamps are invalid", () => {
    const zones = createAnomalyZones([
      { ...baseAnomaly, anomaly_id: "bad-1", timestamp: "bad-date-1" },
      { ...baseAnomaly, anomaly_id: "bad-2", timestamp: "bad-date-2" },
    ]);
    expect(zones).toHaveLength(0);
  });

  it("filters invalid timestamps that do not parse as valid ISO timestamps", () => {
    const zones = createAnomalyZones([
      {
        ...baseAnomaly,
        anomaly_id: "bad-offset",
        timestamp: "2026-07-09T12:00:00+25:00",
      },
    ]);

    expect(zones).toHaveLength(0);
  });

  it("returns null when no telemetry points are available", () => {
    const nearest = findNearestTelemetryPoint(
      "2026-05-19T08:00:00.000Z",
      [],
      5_000
    );
    expect(nearest).toBeNull();
  });

  it("returns the telemetry point closest to anomaly timestamp when within tolerance", () => {
    const points = [
      { timestamp: "2026-05-19T08:00:00.000Z", value: 0.1 },
      { timestamp: "2026-05-19T08:00:04.000Z", value: 0.2 },
      { timestamp: "2026-05-19T08:00:09.000Z", value: 0.3 },
    ];

    const nearest = findNearestTelemetryPoint(
      "2026-05-19T08:00:03.000Z",
      points,
      5_000
    );

    expect(nearest).toEqual(points[1]);
  });

  it("returns null when no telemetry point is within tolerance", () => {
    const points = [
      { timestamp: "2026-05-19T08:00:00.000Z", value: 0.1 },
      { timestamp: "2026-05-19T08:00:20.000Z", value: 0.2 },
    ];

    const nearest = findNearestTelemetryPoint(
      "2026-05-19T08:00:10.000Z",
      points,
      2_000
    );

    expect(nearest).toBeNull();
  });

  it("returns the first telemetry point when two points are equally close", () => {
    const first = { timestamp: "2026-05-19T07:59:55.000Z", value: 0.1 };
    const second = { timestamp: "2026-05-19T08:00:05.000Z", value: 0.2 };

    const nearest = findNearestTelemetryPoint(
      "2026-05-19T08:00:00.000Z",
      [first, second],
      10_000
    );

    expect(nearest).toEqual(first);
  });

  it("matches anomalies within polling-time tolerance", () => {
    const anomaly = { ...baseAnomaly, timestamp: "2026-05-19T08:00:00.000Z" };
    const matched = hasAnomaly("2026-05-19T08:00:03.000Z", [anomaly]);
    expect(matched?.anomaly_id).toBe(anomaly.anomaly_id);
  });

  it("returns null when no anomaly is within tolerance", () => {
    const anomaly = { ...baseAnomaly, timestamp: "2026-05-19T08:00:00.000Z" };
    const matched = hasAnomaly("2026-05-19T08:00:10.000Z", [anomaly]);
    expect(matched).toBeNull();
  });

  it("preserves every event at its recorded time instead of marking nearby samples", () => {
    const earlier = {
      ...baseAnomaly,
      anomaly_id: "earlier",
      timestamp: "2026-05-19T08:00:02.000Z",
    };
    const later = {
      ...baseAnomaly,
      anomaly_id: "later",
      timestamp: "2026-05-19T08:00:04.000Z",
    };
    const markers = createAnomalyMarkers(
      [
        { timestamp: "2026-05-19T08:00:00.000Z", value: 1 },
        { timestamp: "2026-05-19T08:00:01.000Z", value: 2 },
        { timestamp: "2026-05-19T08:00:03.000Z", value: 3 },
        { timestamp: "2026-05-19T08:01:00.000Z", value: 2 },
      ],
      [later, earlier]
    );

    expect(markers).toHaveLength(2);
    expect(markers.map(({ anomaly }) => anomaly.anomaly_id)).toEqual(["earlier", "later"]);
    expect(markers[0]).toMatchObject({
      timestamp: earlier.timestamp,
      time: Date.parse(earlier.timestamp),
      sample: { timestamp: "2026-05-19T08:00:01.000Z", value: 2 },
    });
    expect(markers[1]).toMatchObject({
      timestamp: later.timestamp,
      time: Date.parse(later.timestamp),
      sample: { timestamp: "2026-05-19T08:00:03.000Z", value: 3 },
    });
  });

  it("creates one event marker for dense telemetry and prefers an exact timestamp", () => {
    const markers = createAnomalyMarkers(
      Array.from({ length: 11 }, (_, index) => ({
        timestamp: new Date(Date.parse(baseAnomaly.timestamp) + (index - 5) * 1_000).toISOString(),
        value: index,
      })),
      [baseAnomaly],
    );
    expect(markers).toHaveLength(1);
    expect(markers[0]?.sample).toMatchObject({ time: markers[0]?.time, value: 5 });
  });

  it("chooses the earlier nearest sample on a tie regardless of input order", () => {
    const markers = createAnomalyMarkers([
      { timestamp: "2026-05-19T08:00:03.000Z", value: 3 },
      { timestamp: "2026-05-19T07:59:57.000Z", value: 1 },
    ], [baseAnomaly]);

    expect(markers[0]?.sample?.timestamp).toBe("2026-05-19T07:59:57.000Z");
  });

  it("matches the inclusive five-second boundary but preserves events beyond it without a sample", () => {
    const markers = createAnomalyMarkers([
      { timestamp: "2026-05-19T08:00:05.000Z", value: 3 },
    ], [
      baseAnomaly,
      { ...baseAnomaly, anomaly_id: "outside", timestamp: "2026-05-19T07:59:59.999Z" },
    ]);

    expect(markers).toHaveLength(2);
    expect(markers.find(({ anomaly }) => anomaly.anomaly_id === "outside")?.sample).toBeUndefined();
    expect(markers.find(({ anomaly }) => anomaly.anomaly_id === baseAnomaly.anomaly_id)?.sample?.value).toBe(3);
  });

  it("retains events when telemetry is missing or no finite sample exists", () => {
    expect(createAnomalyMarkers([], [baseAnomaly])[0]).toMatchObject({
      time: Date.parse(baseAnomaly.timestamp),
      anomaly: baseAnomaly,
    });
    const markers = createAnomalyMarkers([
      { timestamp: baseAnomaly.timestamp, value: Number.POSITIVE_INFINITY },
      { timestamp: "invalid", value: 1 },
    ], [baseAnomaly]);
    expect(markers).toHaveLength(1);
    expect(markers[0]?.sample).toBeUndefined();
    expect(markers[0]?.value).toBeUndefined();
  });

  it("uses the last finite duplicate telemetry sample and ignores an invalid replacement", () => {
    const markers = createAnomalyMarkers([
      { timestamp: baseAnomaly.timestamp, value: 1 },
      { timestamp: baseAnomaly.timestamp, value: 2 },
      { timestamp: baseAnomaly.timestamp, value: Number.NaN },
    ], [baseAnomaly]);

    expect(markers[0]?.sample?.value).toBe(2);
  });

  it("deduplicates event IDs while retaining coincident distinct events and the latest valid row", () => {
    const updated = { ...baseAnomaly, anomaly_value: 0.002 };
    const coincident = { ...baseAnomaly, anomaly_id: "anomaly-2" };
    const markers = createAnomalyMarkers([], [
      baseAnomaly,
      coincident,
      updated,
      { ...baseAnomaly, timestamp: "invalid" },
    ]);

    expect(markers).toHaveLength(2);
    expect(markers.map(({ anomaly }) => anomaly.anomaly_id)).toEqual(["anomaly-1", "anomaly-2"]);
    expect(markers[0]?.anomaly.anomaly_value).toBe(0.002);
  });

  it("rejects invalid event timestamps and invalid matching tolerances", () => {
    expect(createAnomalyMarkers([], [{ ...baseAnomaly, timestamp: "invalid" }])).toEqual([]);
    expect(createAnomalyMarkers([], [baseAnomaly], -1)).toEqual([]);
    expect(createAnomalyMarkers([], [baseAnomaly], Number.NaN)).toEqual([]);
  });

  it("supports an exact-match-only tolerance", () => {
    const markers = createAnomalyMarkers([
      { timestamp: baseAnomaly.timestamp, value: 1 },
    ], [
      baseAnomaly,
      { ...baseAnomaly, anomaly_id: "nearby", timestamp: "2026-05-19T08:00:00.001Z" },
    ], 0);

    expect(markers[0]?.sample?.value).toBe(1);
    expect(markers[1]?.sample).toBeUndefined();
  });

  it("filters anomalies by explicit time window", () => {
    const anomalies: Anomaly[] = [
      { ...baseAnomaly, anomaly_id: "inside", timestamp: "2026-05-19T08:00:00.000Z" },
      { ...baseAnomaly, anomaly_id: "outside", timestamp: "2026-05-19T09:00:00.000Z" },
    ];

    const inRange = filterAnomalies(
      anomalies,
      "L1",
      new Date("2026-05-19T07:59:00.000Z"),
      new Date("2026-05-19T08:01:00.000Z")
    );

    expect(inRange).toHaveLength(1);
    expect(inRange[0]?.anomaly_id).toBe("inside");
  });
});
