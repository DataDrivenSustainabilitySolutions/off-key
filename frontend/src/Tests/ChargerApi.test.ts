import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import {
  deleteAnomaly,
  getAllChargers,
  getAllTelemetryData,
  getAnomalyCount,
  getFavorites,
  getTelemetryTypes,
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
