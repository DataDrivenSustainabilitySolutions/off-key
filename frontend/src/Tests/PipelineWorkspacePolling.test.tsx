import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiUtils } from "@/lib/api-client";
import { useMonitoringServices } from "@/features/monitoring/useMonitoringServices";

vi.mock("@/lib/api-client", () => ({
  apiUtils: { get: vi.fn(), patch: vi.fn() },
}));
beforeEach(() => {
  vi.mocked(apiUtils.get).mockResolvedValue({
    services: [],
    authoring_enabled: true,
    selected_service_id: "run",
    pipeline_state: { run_id: "run" },
  });
});

describe("coordinated monitoring snapshots", () => {
  it("discovers the feature and retrieves selected graph status with one request", async () => {
    const hook = renderHook(() => useMonitoringServices(true, 5_000, "run"));
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    expect(apiUtils.get).toHaveBeenCalledExactlyOnceWith(
      "/v1/monitors/workspace?selected_service_id=run",
      expect.objectContaining({ redirectOnUnauthorized: false }),
    );
    expect(hook.result.current.authoringEnabled).toBe(true);
    expect(hook.result.current.pipelineState).toEqual({ run_id: "run" });
    expect(
      vi
        .mocked(apiUtils.get)
        .mock.calls.some(([url]) => /docker|pipeline-state/.test(url)),
    ).toBe(false);
  });
  it("pauses polling while hidden and refreshes on return", async () => {
    vi.useFakeTimers();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const hook = renderHook(() => useMonitoringServices(true, 5_000, "run"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(hook.result.current.ready).toBe(true);
    hidden.mockReturnValue(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(apiUtils.get).toHaveBeenCalledTimes(1);
    hidden.mockReturnValue(false);
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(apiUtils.get).toHaveBeenCalledTimes(2);
  });
});
