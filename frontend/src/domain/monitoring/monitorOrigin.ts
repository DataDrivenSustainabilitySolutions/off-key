import type { MonitorRecord } from "@/types/pipelines.generated";

/**
 * What each step of a monitor's history did. A start right after another one, with no stop
 * between, changed a running monitor: it took a shadow run live, or retuned it.
 */
export function stepLabels(history: readonly MonitorRecord[]): string[] {
  return history.map((record, index) => {
    if (record.event === "stopped") return "Stopped";
    const before = history[index - 1];
    if (!before || before.event === "stopped") return record.shadow ? "Started in shadow" : "Started";
    return before.shadow && !record.shadow ? "Taken live" : "Retuned";
  });
}

/** The chart's rules: each step at its time, named. */
export const historyMarkers = (history: readonly MonitorRecord[]) => {
  const labels = stepLabels(history);
  return history.flatMap((record, index) => {
    const timeMs = Date.parse(record.at);
    return Number.isFinite(timeMs) ? [{ timeMs, label: labels[index]! }] : [];
  });
};
