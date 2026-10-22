import { useSyncExternalStore } from "react";

// One shared timer keeps every relative time on the page in step; the clock
// moves in steps so that repeated reads during one render agree.
const STEP_MS = 15_000;
const listeners = new Set<() => void>();
let timer: number | undefined;
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  timer ??= window.setInterval(() => listeners.forEach(notify => notify()), STEP_MS);
  return () => {
    listeners.delete(listener);
    if (!listeners.size && timer !== undefined) { window.clearInterval(timer); timer = undefined; }
  };
};
const getNow = () => Math.floor(Date.now() / STEP_MS) * STEP_MS;

export function useNow() {
  return useSyncExternalStore(subscribe, getNow, getNow);
}
