import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import {
  deleteAnomaly,
  getAllChargers,
  getAllTelemetryData,
  getAnomalyCount,
  getFavorites,
  getTelemetryCursor,
  getTelemetryTypes,
  mergeTelemetryData,
  toggleFavorite,
} from "@/lib/charger-api";

vi.mock("@/lib/api-client", () => ({
  apiUtils: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockGet = vi.mocked(apiUtils.get);
const mockPost = vi.mocked(apiUtils.post);
const mockDelete = vi.mocked(apiUtils.delete);

describe("charger API", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });

  it("fetches telemetry types from the charger endpoint", async () => {
    mockGet.mockResolvedValueOnce(["controllerCpuUsage"]);

    await expect(getTelemetryTypes("abc-123")).resolves.toEqual([
      "controllerCpuUsage",
    ]);
    expect(mockGet).toHaveBeenCalledWith(
      API_CONFIG.ENDPOINTS.TELEMETRY.TYPES("abc-123"),
    );
  });

  it("loads and categorizes every available telemetry series", async () => {
    mockGet
      .mockResolvedValueOnce(["controllerCpuUsage", "systemVoltage"])
      .mockResolvedValueOnce([{ timestamp: "now", value: 70 }])
      .mockResolvedValueOnce([{ timestamp: "now", value: 230 }]);

    await expect(getAllTelemetryData("charger-1")).resolves.toEqual([
      {
        type: "controllerCpuUsage",
        category: "cpu",
        data: [{ timestamp: "now", value: 70 }],
      },
      {
        type: "systemVoltage",
        category: "system",
        data: [{ timestamp: "now", value: 230 }],
      },
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
      .mockResolvedValueOnce(["systemVoltage"])
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce([finalPoint]);

    const result = await getAllTelemetryData(
      "charger-1",
      undefined,
      new Map([["systemVoltage", initialCursor]]),
    );

    expect(result[0]?.data).toHaveLength(1001);
    expect(mockGet).toHaveBeenNthCalledWith(
      3,
      API_CONFIG.ENDPOINTS.TELEMETRY.DATA(
        "charger-1",
        "systemVoltage",
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

  it("normalizes charger last-seen timestamps", async () => {
    mockGet.mockResolvedValueOnce([
      {
        charger_id: "charger-1",
        charger_name: null,
        last_seen: "database-time",
        mqtt_last_message: "mqtt-time",
        online: true,
        state: "ready",
        created: "created-time",
      },
    ]);

    const chargers = await getAllChargers();

    expect(chargers[0]?.last_seen).toBe("mqtt-time");
  });

  it("fetches favorites and adds or removes them", async () => {
    mockGet.mockResolvedValueOnce(["charger-1"]);

    await expect(getFavorites(7)).resolves.toEqual(["charger-1"]);
    await toggleFavorite("charger-1", 7, false);
    await toggleFavorite("charger-1", 7, true);

    const body = { charger_id: "charger-1", user_id: 7 };
    expect(mockPost).toHaveBeenCalledWith(
      API_CONFIG.ENDPOINTS.FAVORITES.ADD,
      body,
    );
    expect(mockDelete).toHaveBeenCalledWith(
      API_CONFIG.ENDPOINTS.FAVORITES.REMOVE,
      body,
    );
  });

  it("encodes the anomaly count cursor", async () => {
    mockGet.mockResolvedValueOnce({ count: 4 });

    await expect(getAnomalyCount("2026-07-24T10:00:00+02:00")).resolves.toBe(4);
    expect(mockGet).toHaveBeenCalledWith(
      `${API_CONFIG.ENDPOINTS.ANOMALIES.COUNT}?since=2026-07-24T10%3A00%3A00%2B02%3A00`,
    );
  });

  it("rejects an anomaly deletion without an identifier", async () => {
    await expect(deleteAnomaly("")).rejects.toThrow("Anomaly ID is required");
    expect(mockDelete).not.toHaveBeenCalled();
  });
});
