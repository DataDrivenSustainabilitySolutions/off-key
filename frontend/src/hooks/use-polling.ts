import { useCallback, useEffect, useRef } from "react";

export interface PollingOptions {
  /** Delay between runs; without one the loop runs once. */
  intervalMs?: number;
  enabled?: boolean;
  /** Skip automatic runs, the first included, while the page is hidden; an after-completion chain stops until it is visible. */
  pauseWhenHidden?: boolean;
  /** Run as soon as the page becomes visible again. */
  resumeOnVisible?: boolean;
  /** A run while another is pending either aborts it or is skipped. */
  overlap?: "abort-previous" | "skip";
  /** A fixed-rate clock keeps ticking while a run hangs; after-completion waits for it. */
  schedule?: "fixed-rate" | "after-completion";
  /** Run the first tick inside the effect instead of on the next task. */
  startImmediately?: boolean;
  /** Runs on every tick, including ticks that a pending run makes skip. */
  onTick?: () => void;
}

type Tick = (signal: AbortSignal) => Promise<void> | void;
const idle = { reload: () => Promise.resolve(), abort: () => {} };

/**
 * One owner for a poller's timers, its per-run AbortController and its
 * teardown. The tick handles its own errors and checks `signal.aborted`
 * before writing state; the loop restarts whenever `tick` or an option changes.
 * `reload` aborts the in-flight run and restarts the schedule.
 */
export function usePollingLoop(tick: Tick, {
  intervalMs, enabled = true, pauseWhenHidden = false, resumeOnVisible = false,
  overlap = "abort-previous", schedule = "fixed-rate", startImmediately = false, onTick,
}: PollingOptions = {}) {
  const controls = useRef(idle);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    let controller: AbortController | undefined;
    let pending = false;
    let next: ReturnType<typeof setTimeout> | undefined;
    const execute = async (manual = false) => {
      if (!active) return;
      onTick?.();
      if (pending && overlap === "skip" && !manual) return;
      clearTimeout(next);
      controller?.abort();
      const current = new AbortController();
      controller = current;
      pending = true;
      try {
        await tick(current.signal);
      } catch {
        // The tick reports its own failures.
      } finally {
        if (controller === current) pending = false;
        if (schedule === "after-completion" && intervalMs !== undefined && active && !current.signal.aborted) {
          next = setTimeout(scheduled, intervalMs);
        }
      }
    };
    const scheduled = () => { if (!(pauseWhenHidden && document.hidden)) void execute(); };
    const visible = () => { if (!document.hidden) void execute(); };
    let clock: ReturnType<typeof setInterval> | undefined;
    if (schedule === "fixed-rate" && intervalMs !== undefined) clock = setInterval(scheduled, intervalMs);
    if (resumeOnVisible) document.addEventListener("visibilitychange", visible);
    if (startImmediately) scheduled();
    else next = setTimeout(scheduled, 0);
    controls.current = { reload: () => execute(true), abort: () => controller?.abort() };
    return () => {
      active = false;
      controls.current = idle;
      clearTimeout(next);
      clearInterval(clock);
      controller?.abort();
      if (resumeOnVisible) document.removeEventListener("visibilitychange", visible);
    };
  }, [tick, enabled, intervalMs, pauseWhenHidden, resumeOnVisible, overlap, schedule, startImmediately, onTick]);
  const reload = useCallback(() => controls.current.reload(), []);
  const abort = useCallback(() => controls.current.abort(), []);
  return { reload, abort };
}
