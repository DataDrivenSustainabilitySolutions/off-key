import { useCallback, useSyncExternalStore } from "react";

// One shared timer per step keeps every clock on the page in step, and every
// read between two ticks agrees. Hidden pages skip ticks and catch up when
// they become visible again.
type Clock = { listeners: Set<() => void>; notify: () => void; now: number; timer?: number };
const clocks = new Map<number, Clock>();
const noSubscription = () => () => {};
const stepped = (stepMs: number) => Math.floor(Date.now() / stepMs) * stepMs;

function subscribeTo(stepMs: number, listener: () => void) {
  let clock = clocks.get(stepMs);
  if (!clock) {
    const listeners = new Set<() => void>();
    const notify = () => {
      if (document.hidden) return;
      created.now = Date.now();
      listeners.forEach(update => update());
    };
    // Starting on the stepped time keeps the first subscription from re-rendering.
    const created: Clock = { listeners, notify, now: stepped(stepMs) };
    clock = created;
    clocks.set(stepMs, clock);
    clock.timer = window.setInterval(clock.notify, stepMs);
    document.addEventListener("visibilitychange", clock.notify);
  }
  const shared = clock;
  shared.listeners.add(listener);
  return () => {
    shared.listeners.delete(listener);
    if (shared.listeners.size) return;
    window.clearInterval(shared.timer);
    document.removeEventListener("visibilitychange", shared.notify);
    clocks.delete(stepMs);
  };
}

/** The current time, refreshed every `stepMs`; `enabled: false` stops it ticking. */
export function useNow(stepMs = 15_000, enabled = true) {
  const subscribe = useCallback((listener: () => void) => subscribeTo(stepMs, listener), [stepMs]);
  // A running clock reports its last tick; a stopped one reads the time in steps.
  const getNow = useCallback(() => clocks.get(stepMs)?.now ?? stepped(stepMs), [stepMs]);
  return useSyncExternalStore(enabled ? subscribe : noSubscription, getNow, getNow);
}
