import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getTelemetryRange } from "@/lib/charger-api";
import { rangePreset, useStoredRange } from "@/features/readings/useStoredRange";

vi.mock("@/lib/charger-api", () => ({ getTelemetryRange: vi.fn() }));
const NOW = Date.parse("2026-10-28T12:00:00Z");
const binding = { entityId: "entity", telemetryType: "voltage" };
const point = (time: number, value: number) => ({ timestamp: new Date(time).toISOString(), value });

beforeEach(() => { vi.spyOn(Date, "now").mockReturnValue(NOW); });
afterEach(() => { vi.restoreAllMocks(); vi.mocked(getTelemetryRange).mockReset(); vi.useRealTimers(); });

describe("stored telemetry ranges", () => {
  it("asks for the chosen span, or for everything stored", async () => {
    vi.mocked(getTelemetryRange).mockResolvedValue([point(NOW - 1000, 1)]);
    const hook = renderHook(({ span }) => useStoredRange(binding, span), { initialProps: { span: rangePreset("1d").spanMs as number | undefined } });
    await waitFor(() => expect(hook.result.current).toEqual([point(NOW - 1000, 1)]));
    expect(getTelemetryRange).toHaveBeenLastCalledWith("entity", "voltage", { startMs: NOW - 86_400_000, buckets: 600 }, expect.any(AbortSignal));
    hook.rerender({ span: rangePreset("all").spanMs });
    expect(hook.result.current).toEqual([]);
    await waitFor(() => expect(getTelemetryRange).toHaveBeenLastCalledWith("entity", "voltage", { startMs: undefined, buckets: 600 }, expect.any(AbortSignal)));
  });

  it("swaps in finer points across the inspected window only", async () => {
    vi.mocked(getTelemetryRange).mockImplementation(async (_entity, _type, range) => range.endMs === undefined
      ? [point(NOW - 3000, 1), point(NOW - 2000, 50), point(NOW - 1000, 3)]
      : [point(NOW - 2500, 20), point(NOW - 2000, 50), point(NOW - 1500, 30)]);
    const hook = renderHook(({ window }) => useStoredRange(binding, undefined, window),
      { initialProps: { window: undefined as { startMs: number; endMs: number } | undefined } });
    await waitFor(() => expect(hook.result.current).toHaveLength(3));
    hook.rerender({ window: { startMs: NOW - 2600, endMs: NOW - 1400 } });
    await waitFor(() => expect(hook.result.current.map(({ value }) => value)).toEqual([1, 20, 50, 30, 3]));
    act(() => hook.rerender({ window: undefined }));
    expect(hook.result.current.map(({ value }) => value)).toEqual([1, 50, 3]);
  });

  it("stays idle for a reading that is not recorded", () => {
    const hook = renderHook(() => useStoredRange(undefined, 3_600_000));
    expect(hook.result.current).toEqual([]);
    expect(getTelemetryRange).not.toHaveBeenCalled();
  });
});
