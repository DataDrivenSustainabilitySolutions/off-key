// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { epochMicroseconds, epochMilliseconds, isoTimestamp, compareTimestamps } from "@/lib/timestamps";
import { mergeReadingHistory } from "@/domain/readings/readingMonitoring";
import { normalizeTelemetry } from "@/features/charts/telemetry-data";
import { getTelemetryCursor } from "@/lib/charger-api";
import { getMonitoringEvidenceCursor, filterServiceAnomalies } from "@/lib/monitoring-chart";
import { alarm, chartEvidence } from "./support/fixtures/monitoring";
import { formatMonitoringObservationTooltip } from "@/features/charts/monitoring-tooltip";

vi.mock("@/lib/api-client", () => ({ apiUtils: {} }));

const early = "2026-11-07T00:00:00.000001Z";
const late = "2026-11-07T00:00:00.000999Z";

describe("observation timestamp precision", () => {
  it("normalizes timezone and fraction spellings without dropping microseconds", () => {
    expect(epochMicroseconds(early)).toBe(epochMicroseconds("2026-11-07T01:00:00.000001+01:00"));
    expect(epochMicroseconds("1969-12-31T23:59:59.999999Z")).toBe(-1n);
    expect(compareTimestamps(early, late)).toBe(-1);
    expect(epochMicroseconds("invalid")).toBeUndefined();
    expect(isoTimestamp(epochMilliseconds(early))).toBe(early);
    expect(isoTimestamp(epochMilliseconds(late))).toBe(late);
  });

  it("keeps a spike and its following sample within the same millisecond", () => {
    const points = [{ timestamp: early, value: 1000 }, { timestamp: late, value: 1 }];
    expect(mergeReadingHistory([], points)).toEqual(points);
    expect(normalizeTelemetry(points)).toEqual([[epochMilliseconds(early), 1000], [epochMilliseconds(late), 1]]);
    expect(epochMilliseconds(late)).toBeGreaterThan(epochMilliseconds(early));
    expect(mergeReadingHistory(points, [{ timestamp: "2026-11-07T01:00:00.000001+01:00", value: 999 }]))
      .toHaveLength(2);
  });

  it("advances telemetry and evidence cursors in the database's full order", () => {
    expect(getTelemetryCursor([
      { created: early, timestamp: early, value: 1 }, { created: late, timestamp: late, value: 2 },
    ])).toEqual({ created: late, timestamp: late });
    const rows = [
      chartEvidence({ created: early, timestamp: early, monitor_id: "z", sequence_number: 99 }),
      chartEvidence({ created: late, timestamp: early, monitor_id: "a", sequence_number: 1 }),
    ];
    expect(getMonitoringEvidenceCursor(rows)).toEqual({ created: late, timestamp: early, monitor_id: "a", sequence_number: 1 });
  });

  it("does not attribute a neighboring microsecond alarm to a detector", () => {
    const rows = [chartEvidence({ monitor_id: "m", timestamp: early, alarm: true, input_timestamps: { r: early } })];
    const matching = alarm({ timestamp: early, monitor_id: null });
    expect(filterServiceAnomalies([matching, alarm({ timestamp: late, monitor_id: null })], rows, "m", "r"))
      .toEqual([matching]);
  });

  it("matches the exact input in a detector tooltip", () => {
    const time = epochMilliseconds(early);
    const text = formatMonitoringObservationTooltip([
      { seriesId: "r", value: [time, 1000] },
      { seriesId: "score", seriesName: "Score", value: [time, 0.9], data: { observation: {
        timeMs: time, inputTimestamps: { r: early }, value: 0.9, threshold: 0.5, alarmActive: true,
      } } },
    ], [{ id: "r", name: "Reading", inputKey: "r", data: [[time, 1000]],
      pendingTelemetry: [], anomalyMarkers: [], color: "blue" }], String, String);
    expect(text).toContain("Reading: 1000");
    expect(text).toContain("Alarm: active");
    expect(text).not.toContain("No evaluated result");
  });
});
