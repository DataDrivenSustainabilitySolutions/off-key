import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getTelemetryHistory } from "@/lib/charger-api";
import { overviewRefreshMs, useStoredRange } from "@/features/readings/useStoredRange";
import type { HistoryPreference, TelemetryHistory } from "@/types/telemetry-history";

vi.mock("@/lib/charger-api", () => ({ getTelemetryHistory: vi.fn() }));
const NOW = Date.parse("2026-10-28T12:00:00Z");
const binding = { readingId: "voltage" };
const data: TelemetryHistory = { representation: "raw", points: [{ timestamp: new Date(NOW - 1000).toISOString(), value: 1 }],
  interval_ms: 0, sample_count: 1, extent: [new Date(NOW - 1000).toISOString(), new Date(NOW - 1000).toISOString()], truncated: false };

beforeEach(() => { vi.spyOn(Date, "now").mockReturnValue(NOW); vi.mocked(getTelemetryHistory).mockResolvedValue(data); });
const setHidden = (hidden: boolean) => {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  document.dispatchEvent(new Event("visibilitychange"));
};
afterEach(() => { setHidden(false); vi.restoreAllMocks(); vi.mocked(getTelemetryHistory).mockReset(); vi.useRealTimers(); });

describe("stored telemetry ranges", () => {
  it("requests true statistics for the selected range and original samples on demand", async () => {
    const hook = renderHook(({ span, preference }) => useStoredRange(binding, span, undefined, preference, 120), {
      initialProps: { span: 86_400_000 as number | undefined, preference: { mode: "auto" } as HistoryPreference },
    });
    await waitFor(() => expect(hook.result.current.history).toEqual(data));
    expect(getTelemetryHistory).toHaveBeenLastCalledWith("voltage", { startMs: NOW - 86_400_000, buckets: 120, view: "auto", windowMs: undefined }, expect.any(AbortSignal));
    hook.rerender({ span: undefined, preference: { mode: "raw" } });
    await waitFor(() => expect(getTelemetryHistory).toHaveBeenLastCalledWith("voltage", { startMs: undefined, buckets: 120, view: "raw", windowMs: undefined }, expect.any(AbortSignal)));
  });

  it("preserves the overview and refetches the same inspected interval when switching to raw", async () => {
    const hook = renderHook(({ window, preference }) => useStoredRange(binding, undefined, window, preference),
      { initialProps: { window: undefined as { startMs: number; endMs: number } | undefined, preference: { mode: "auto" } as HistoryPreference } });
    await waitFor(() => expect(hook.result.current.history).toEqual(data));
    const window = { startMs: NOW - 2600, endMs: NOW - 1400 };
    hook.rerender({ window, preference: { mode: "auto" } });
    await waitFor(() => expect(getTelemetryHistory).toHaveBeenLastCalledWith("voltage", { ...window, buckets: 100, view: "auto", windowMs: undefined }, expect.any(AbortSignal)));
    hook.rerender({ window, preference: { mode: "raw" } });
    await waitFor(() => expect(getTelemetryHistory).toHaveBeenLastCalledWith("voltage", { ...window, buckets: 100, view: "raw", windowMs: undefined }, expect.any(AbortSignal)));
    expect(hook.result.current.overview).toEqual(data);
  });

  it("never reuses another reading's history after a late response", async () => {
    let finish!: (value: TelemetryHistory) => void;
    vi.mocked(getTelemetryHistory).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const hook = renderHook(({ readingId }) => useStoredRange({ readingId }, 3_600_000), { initialProps: binding });
    hook.rerender({ readingId: "other" });
    await waitFor(() => expect(hook.result.current.history).toEqual(data));
    await act(async () => { finish({ ...data, points: [] }); });
    expect(hook.result.current.history).toEqual(data);
  });

  it("reports a failed history request instead of labelling a fallback as raw history", async () => {
    vi.mocked(getTelemetryHistory).mockRejectedValue(new Error("offline"));
    const hook = renderHook(() => useStoredRange(binding, 3_600_000));
    await waitFor(() => expect(hook.result.current.error).toMatch(/could not be updated/));
    expect(hook.result.current.history).toBeUndefined();
    expect(hook.result.current.loading).toBe(false);
  });

  it("asks for the overview as often as its means can change", () => {
    expect(overviewRefreshMs(60_000, { mode: "auto" }, 300)).toBe(5_000);
    expect(overviewRefreshMs(3_600_000, { mode: "auto" }, 300)).toBe(7_500);
    expect(overviewRefreshMs(3_600_000, { mode: "auto", windowMs: 60_000 }, 300)).toBe(30_000);
    expect(overviewRefreshMs(86_400_000, { mode: "auto" }, 300)).toBe(60_000);
    // Original samples and the whole history refresh each minute; live values are appended meanwhile.
    expect(overviewRefreshMs(3_600_000, { mode: "raw" }, 300)).toBe(60_000);
    expect(overviewRefreshMs(undefined, { mode: "auto" }, 300)).toBe(60_000);
  });

  it("loads an inspected window once and asks again only after a failed request", async () => {
    vi.useFakeTimers();
    vi.mocked(getTelemetryHistory).mockRejectedValueOnce(new Error("offline"));
    const window = { startMs: NOW - 2600, endMs: NOW - 1400 };
    const hook = renderHook(() => useStoredRange(binding, 3_600_000, window));
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(getTelemetryHistory).toHaveBeenCalledTimes(1);
    expect(hook.result.current.error).toMatch(/could not be loaded/);
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(getTelemetryHistory).toHaveBeenCalledTimes(2);
    expect(hook.result.current).toMatchObject({ history: data, error: "" });
    // The window is fixed, so its history is too: nothing asks for it again.
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(getTelemetryHistory).toHaveBeenCalledTimes(2);
  });

  it("retries a failed window again once a hidden page is shown", async () => {
    vi.useFakeTimers();
    vi.mocked(getTelemetryHistory).mockRejectedValueOnce(new Error("offline"));
    const hook = renderHook(() => useStoredRange(binding, 3_600_000, { startMs: NOW - 2600, endMs: NOW - 1400 }));
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(hook.result.current.error).toMatch(/could not be loaded/);
    // The retry falls due while nobody is looking, so it waits.
    await act(async () => { setHidden(true); await vi.advanceTimersByTimeAsync(60_000); });
    expect(getTelemetryHistory).toHaveBeenCalledTimes(1);
    await act(async () => { setHidden(false); await vi.advanceTimersByTimeAsync(0); });
    expect(getTelemetryHistory).toHaveBeenCalledTimes(2);
    expect(hook.result.current).toMatchObject({ history: data, error: "" });
  });

  it("does not fetch for a reading that is not recorded", () => {
    const hook = renderHook(() => useStoredRange(undefined, 3_600_000));
    expect(hook.result.current.history).toBeUndefined();
    expect(getTelemetryHistory).not.toHaveBeenCalled();
  });
});
