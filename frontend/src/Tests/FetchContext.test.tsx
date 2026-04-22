import React from "react";
import { renderHook, act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { FetchContext, FetchProvider } from "../dataFetch/FetchContext";

vi.mock("@/lib/api-client", () => ({
  apiUtils: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockApiUtils = apiUtils as unknown as {
  get: ReturnType<typeof vi.fn>;
  post: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
};

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <FetchProvider>{children}</FetchProvider>
);

describe("FetchContext logic", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });

  it("fetches telemetry types", async () => {
    mockApiUtils.get.mockResolvedValueOnce(["controllerCpuUsage"]);

    const { result } = renderHook(() => React.useContext(FetchContext), {
      wrapper,
    });
    const types = await result.current?.getTelemetryTypes?.("abc-123");

    expect(types).toEqual(["controllerCpuUsage"]);
    expect(mockApiUtils.get).toHaveBeenCalledWith(
      API_CONFIG.ENDPOINTS.TELEMETRY.TYPES("abc-123")
    );
  });

  it("fetches favorites", async () => {
    mockApiUtils.get.mockResolvedValueOnce(["abc123"]);

    const { result } = renderHook(() => React.useContext(FetchContext), {
      wrapper,
    });
    const favorites = await result.current?.getFavorites?.(1);

    expect(favorites).toEqual(["abc123"]);
    expect(mockApiUtils.get).toHaveBeenCalledWith(
      API_CONFIG.ENDPOINTS.FAVORITES.GET(1)
    );
  });

  it("adds a favorite", async () => {
    mockApiUtils.post.mockResolvedValueOnce(undefined);

    const { result } = renderHook(() => React.useContext(FetchContext), {
      wrapper,
    });
    await act(async () => {
      await result.current?.toggleFavorite?.("charger-1", 1, false);
    });

    expect(mockApiUtils.post).toHaveBeenCalledWith(
      API_CONFIG.ENDPOINTS.FAVORITES.ADD,
      { charger_id: "charger-1", user_id: 1 }
    );
  });

  it("removes a favorite", async () => {
    mockApiUtils.delete.mockResolvedValueOnce(undefined);

    const { result } = renderHook(() => React.useContext(FetchContext), {
      wrapper,
    });
    await act(async () => {
      await result.current?.toggleFavorite?.("charger-1", 1, true);
    });

    expect(mockApiUtils.delete).toHaveBeenCalledWith(
      API_CONFIG.ENDPOINTS.FAVORITES.REMOVE,
      { charger_id: "charger-1", user_id: 1 }
    );
  });

  it("loads CPU usage data correctly", async () => {
    mockApiUtils.get
      .mockResolvedValueOnce(["controllerCpuUsage"])
      .mockResolvedValueOnce([{ timestamp: "now", value: 70 }]);

    const { result } = renderHook(() => React.useContext(FetchContext), {
      wrapper,
    });
    await act(async () => {
      await result.current?.loadCpuUsage?.("chargerX");
    });

    const data = result.current?.cpuUsageMap["chargerX"];
    expect(data?.[0].value).toBe(70);
  });

  it("sets searchError when telemetry types are not found", async () => {
    mockApiUtils.get.mockResolvedValueOnce([]);

    const { result } = renderHook(() => React.useContext(FetchContext), {
      wrapper,
    });
    await act(async () => {
      await result.current?.loadCpuUsage?.("chargerY");
    });

    expect(result.current?.searchError).toBe(true);
  });
});
