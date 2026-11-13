// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import {
  deleteAlarm,
  getAllTelemetryData,
  getTelemetryCursor,
  getTelemetryHistory,
  mergeTelemetryData,
} from "@/lib/charger-api";

vi.mock("@/lib/api-client", () => ({
  apiUtils: {
    get: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockGet = vi.mocked(apiUtils.get);
const mockDelete = vi.mocked(apiUtils.delete);

const readings = [
  { id: "reading:cpu", label: "CPU", category: "Processor" },
  { id: "reading:voltage", label: "", category: "" },
];

describe("measurement API", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });

  it("names each reading by its catalogue id in the measurement and bucket paths", () => {
    expect(API_CONFIG.ENDPOINTS.READINGS.MEASUREMENTS("reading:cpu", 50, {
      created: "2026-01-01T00:00:02Z", timestamp: "2026-01-01T00:00:01Z",
    })).toBe(
      "/v1/readings/reading%3Acpu/measurements?limit=50"
      + "&after_created=2026-01-01T00%3A00%3A02Z&after_event_timestamp=2026-01-01T00%3A00%3A01Z",
    );
    expect(API_CONFIG.ENDPOINTS.READINGS.BUCKETS("reading:cpu", { buckets: 600 }))
      .toBe("/v1/readings/reading%3Acpu/measurements/buckets?buckets=600");
  });

  it("asks chart evidence for a device or for each named reading", () => {
    const device = new URL(API_CONFIG.ENDPOINTS.MONITORING.CHART_EVIDENCE({ deviceId: "device:pump" }), "http://app.test");
    expect(device.searchParams.get("device_id")).toBe("device:pump");
    const named = new URL(API_CONFIG.ENDPOINTS.MONITORING.CHART_EVIDENCE(
      { readingIds: ["reading:a", "reading:b"] },
      { created: "c", timestamp: "t", monitor_id: "m0", sequence_number: 4 },
      "m1",
    ), "http://app.test");
    expect(named.searchParams.getAll("reading_id")).toEqual(["reading:a", "reading:b"]);
    expect(named.searchParams.get("monitor_id")).toBe("m1");
    expect(named.searchParams.get("after_monitor_id")).toBe("m0");
  });

  it("does not pass legacy extrema off as original samples or averages", async () => {
    mockGet.mockResolvedValueOnce([{ timestamp: "2026-01-01T00:00:00Z", value: 1 }]);
    await expect(getTelemetryHistory("reading:cpu", { view: "auto" })).rejects.toThrow("automatic history views");
  });

  it("loads one series per catalogue reading, keyed by its id", async () => {
    const signal = new AbortController().signal;
    mockGet
      .mockResolvedValueOnce([{ timestamp: "now", value: 70 }])
      .mockResolvedValueOnce([{ timestamp: "now", value: 230 }]);

    await expect(getAllTelemetryData(readings, signal)).resolves.toEqual([
      { type: "reading:cpu", label: "CPU", category: "Processor", data: [{ timestamp: "now", value: 70 }] },
      { type: "reading:voltage", category: "Other", data: [{ timestamp: "now", value: 230 }] },
    ]);
    expect(mockGet).toHaveBeenCalledWith(API_CONFIG.ENDPOINTS.READINGS.MEASUREMENTS("reading:cpu", 1000), { signal });
  });

  it("leaves out a reading whose values could not be loaded", async () => {
    mockGet
      .mockResolvedValueOnce([{ timestamp: "now", value: 70 }])
      .mockRejectedValueOnce(new Error("unavailable"));

    await expect(getAllTelemetryData(readings)).resolves.toEqual([
      { type: "reading:cpu", label: "CPU", category: "Processor", data: [{ timestamp: "now", value: 70 }] },
    ]);
  });

  it("advances telemetry cursors by ingestion order", () => {
    expect(getTelemetryCursor([
      {
        timestamp: "2026-01-01T00:00:02Z",
        created: "2026-01-01T00:00:10Z",
        value: 2,
      },
      {
        timestamp: "2026-01-01T00:00:01Z",
        created: "2026-01-01T00:00:20Z",
        value: 1,
      },
    ])).toEqual({
      created: "2026-01-01T00:00:20Z",
      timestamp: "2026-01-01T00:00:01Z",
    });
  });

  it("skips telemetry with an invalid event-time cursor field", () => {
    const valid = {
      timestamp: "2026-01-01T00:00:01Z",
      created: "2026-01-01T00:00:10Z",
      value: 2,
    };

    expect(getTelemetryCursor([
      { ...valid, timestamp: "not-a-date" },
      valid,
    ])).toEqual({
      created: valid.created,
      timestamp: valid.timestamp,
    });
  });

  it("drains every full forward telemetry page before advancing", async () => {
    const firstPage = Array.from({ length: 1000 }, (_, index) => ({
      timestamp: new Date(Date.UTC(2026, 0, 1, 0, 0, index)).toISOString(),
      created: new Date(Date.UTC(2026, 0, 1, 1, 0, index)).toISOString(),
      value: index,
    }));
    const finalPoint = {
      timestamp: "2026-01-01T00:20:00.000Z",
      created: "2026-01-01T01:20:00.000Z",
      value: 1000,
    };
    const initialCursor = {
      created: "2026-01-01T00:59:59.000Z",
      timestamp: "2025-12-31T23:59:59.000Z",
    };
    mockGet
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce([finalPoint]);

    const result = await getAllTelemetryData(
      [readings[1]!],
      undefined,
      new Map([["reading:voltage", initialCursor]]),
    );

    expect(result[0]?.data).toHaveLength(1001);
    expect(mockGet).toHaveBeenNthCalledWith(
      1,
      API_CONFIG.ENDPOINTS.READINGS.MEASUREMENTS("reading:voltage", 1000, initialCursor),
    );
    expect(mockGet).toHaveBeenNthCalledWith(
      2,
      API_CONFIG.ENDPOINTS.READINGS.MEASUREMENTS(
        "reading:voltage",
        1000,
        getTelemetryCursor(firstPage),
      ),
    );
  });

  it("merges incremental telemetry while preserving unchanged series references", () => {
    const unchanged = {
      type: "systemVoltage",
      category: "system" as const,
      data: [{ timestamp: "2026-01-01T00:00:01Z", value: 230 }],
    };
    const current = [unchanged];

    expect(mergeTelemetryData(current, [{ ...unchanged, data: [] }])).toBe(current);

    const merged = mergeTelemetryData(current, [
      {
        ...unchanged,
        data: [{ timestamp: "2026-01-01T00:00:02Z", value: 231 }],
      },
    ]);
    expect(merged[0]?.data.map((point) => point.value)).toEqual([231, 230]);

    expect(mergeTelemetryData(current, [])).toBe(current);
  });

  it("preserves existing telemetry when one incremental request fails", () => {
    const existing = {
      type: "systemVoltage",
      category: "system" as const,
      data: [{ timestamp: "2026-01-01T00:00:01Z", value: 230 }],
    };
    const added = {
      type: "controllerCpuUsage",
      category: "cpu" as const,
      data: [{ timestamp: "2026-01-01T00:00:01Z", value: 70 }],
    };

    expect(mergeTelemetryData([existing], [added])).toEqual([existing, added]);
  });

  it("applies catalog name and category edits even when no new telemetry arrives", () => {
    const existing = {
      type: "systemVoltage",
      category: "Voltage",
      label: "Original voltage",
      data: [{ timestamp: "2026-01-01T00:00:01Z", value: 230 }],
      cursor: { created: "2026-01-01T00:00:02Z", timestamp: "2026-01-01T00:00:01Z" },
    };
    const merged = mergeTelemetryData([existing], [{
      type: existing.type,
      category: "Electrical",
      label: "Renamed voltage",
      data: [],
    }]);

    expect(merged).toEqual([{ ...existing, category: "Electrical", label: "Renamed voltage" }]);
    expect(merged[0]?.data).toBe(existing.data);
  });

  it("asks for a device's alarms by device, and other alarms reading by reading", () => {
    expect(API_CONFIG.ENDPOINTS.ALARMS.LIST({ deviceId: "pump/1" })).toBe("/v1/alarms?device_id=pump%2F1");
    expect(API_CONFIG.ENDPOINTS.ALARMS.LIST({ readingIds: ["wind", "rain"] })).toBe("/v1/alarms?reading_id=wind&reading_id=rain");
    expect(API_CONFIG.ENDPOINTS.ALARMS.DELETE("a/1")).toBe("/v1/alarms/a%2F1");
  });

  it("rejects an alarm deletion without an identifier", async () => {
    await expect(deleteAlarm("")).rejects.toThrow("Alarm ID is required");
    expect(mockDelete).not.toHaveBeenCalled();
  });
});
