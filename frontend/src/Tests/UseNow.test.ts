import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useNow } from "@/hooks/use-now";

describe("shared clock", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"], now: 1_000_500 }); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it("ticks every step, shares one timer, stops when disabled and catches up after a hidden page", () => {
    const interval = vi.spyOn(window, "setInterval");
    const first = renderHook(() => useNow(1000));
    const second = renderHook(() => useNow(1000));
    const stopped = renderHook(() => useNow(5000, false));
    expect(interval).toHaveBeenCalledTimes(1);
    expect(first.result.current).toBe(1_000_000);
    act(() => { vi.advanceTimersByTime(1000); });
    expect(first.result.current).toBe(1_001_500);
    expect(second.result.current).toBe(1_001_500);
    expect(stopped.result.current).toBe(1_000_000);
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    act(() => { vi.advanceTimersByTime(3000); });
    expect(first.result.current).toBe(1_001_500);
    hidden.mockReturnValue(false);
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(first.result.current).toBe(1_004_500);
    first.unmount(); second.unmount(); stopped.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
