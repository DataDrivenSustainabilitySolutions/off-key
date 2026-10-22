import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePollingLoop, type PollingOptions } from "@/hooks/use-polling";

type Run = { signal: AbortSignal; finish: () => void };

function harness(options: PollingOptions) {
  const runs: Run[] = [];
  const tick = (signal: AbortSignal) => new Promise<void>(resolve => runs.push({ signal, finish: resolve }));
  const hook = renderHook(({ opts }) => usePollingLoop(tick, opts), { initialProps: { opts: options } });
  return { runs, hook };
}
const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));
const setHidden = (hidden: boolean) => {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  document.dispatchEvent(new Event("visibilitychange"));
};

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); setHidden(false); });

describe("usePollingLoop", () => {
  it("starts on the next task unless asked to start immediately", async () => {
    const deferred = harness({});
    expect(deferred.runs).toHaveLength(0);
    await advance(0);
    expect(deferred.runs).toHaveLength(1);

    const immediate = harness({ startImmediately: true });
    expect(immediate.runs).toHaveLength(1);
  });

  it("runs once without an interval", async () => {
    const { runs } = harness({});
    await advance(0);
    runs[0]!.finish();
    await advance(60_000);
    expect(runs).toHaveLength(1);
  });

  it("aborts a hanging run when the fixed-rate clock ticks", async () => {
    const { runs } = harness({ intervalMs: 1000 });
    await advance(0);
    await advance(1000);
    expect(runs).toHaveLength(2);
    expect(runs[0]!.signal.aborted).toBe(true);
    expect(runs[1]!.signal.aborted).toBe(false);
  });

  it("skips ticks while a run is pending but keeps the clock", async () => {
    const onTick = vi.fn();
    const { runs } = harness({ intervalMs: 1000, overlap: "skip", startImmediately: true, onTick });
    await advance(3000);
    expect(runs).toHaveLength(1);
    expect(onTick).toHaveBeenCalledTimes(4);
    await act(async () => runs[0]!.finish());
    await advance(1000);
    expect(runs).toHaveLength(2);
  });

  it("waits for completion before scheduling the next run", async () => {
    const { runs } = harness({ intervalMs: 1000, schedule: "after-completion" });
    await advance(0);
    await advance(5000);
    expect(runs).toHaveLength(1);
    await act(async () => runs[0]!.finish());
    await advance(999);
    expect(runs).toHaveLength(1);
    await advance(1);
    expect(runs).toHaveLength(2);
  });

  it("gives reload precedence and restarts an after-completion schedule", async () => {
    const { runs, hook } = harness({ intervalMs: 1000, schedule: "after-completion" });
    await advance(0);
    await act(async () => runs[0]!.finish());
    await advance(500);
    let reloaded: Promise<void> | undefined;
    act(() => { reloaded = hook.result.current.reload(); });
    expect(runs).toHaveLength(2);
    await advance(500);
    expect(runs).toHaveLength(2);
    await act(async () => { runs[1]!.finish(); await reloaded; });
    await advance(1000);
    expect(runs).toHaveLength(3);
  });

  it("reload aborts the pending run even when overlap is skipped", async () => {
    const { runs, hook } = harness({ intervalMs: 1000, overlap: "skip" });
    await advance(0);
    act(() => { void hook.result.current.reload(); });
    expect(runs).toHaveLength(2);
    expect(runs[0]!.signal.aborted).toBe(true);
  });

  it("pauses while hidden and resumes when visible", async () => {
    const { runs } = harness({ intervalMs: 1000, pauseWhenHidden: true, resumeOnVisible: true });
    await advance(0);
    runs[0]!.finish();
    setHidden(true);
    await advance(5000);
    expect(runs).toHaveLength(1);
    act(() => setHidden(false));
    expect(runs).toHaveLength(2);
  });

  it("aborts and stops on unmount and when disabled", async () => {
    const { runs, hook } = harness({ intervalMs: 1000 });
    await advance(0);
    hook.rerender({ opts: { intervalMs: 1000, enabled: false } });
    expect(runs[0]!.signal.aborted).toBe(true);
    await advance(5000);
    expect(runs).toHaveLength(1);
    await expect(hook.result.current.reload()).resolves.toBeUndefined();
    expect(runs).toHaveLength(1);

    hook.rerender({ opts: { intervalMs: 1000 } });
    await advance(0);
    expect(runs).toHaveLength(2);
    hook.unmount();
    expect(runs[1]!.signal.aborted).toBe(true);
    await advance(5000);
    expect(runs).toHaveLength(2);
  });

  it("swallows a failing tick and keeps polling", async () => {
    const tick = vi.fn(() => Promise.reject(new Error("offline")));
    renderHook(() => usePollingLoop(tick, { intervalMs: 1000 }));
    await advance(0);
    await advance(1000);
    expect(tick).toHaveBeenCalledTimes(2);
  });

  it("waits one interval without an initial run and aborts the pending run when hidden", async () => {
    const { runs } = harness({ intervalMs: 1000, overlap: "skip", initialRun: false, pauseWhenHidden: true,
      resumeOnVisible: true, abortWhenHidden: true });
    await advance(999);
    expect(runs).toHaveLength(0);
    await advance(1);
    expect(runs).toHaveLength(1);
    act(() => setHidden(true));
    expect(runs[0]!.signal.aborted).toBe(true);
    runs[0]!.finish();
    await advance(5000);
    expect(runs).toHaveLength(1);
    act(() => setHidden(false));
    expect(runs).toHaveLength(2);
  });
});
