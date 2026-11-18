import { createContext } from "react";
import type { Autocorrelation } from "@/types/dojo.generated";

/** The readings a design is set up for, so a step can show how they relate to their past. */
export const LagReadingsContext = createContext<{ id: string; label: string }[]>([]);

/** What a reading's profile says about its past, as the Lags step reads it. */
export type LagProfile = { autocorrelation: Autocorrelation[]; notes: string[] };

// Lags this correlated with each other carry nearly the same information.
const REDUNDANT = 0.95;
const MAX_LAGS = 24;

type Unit = { short: string; seconds?: number };

/** Suggested lags in a step's unit, distinct and in order; none where the unit cannot hold them. */
export function suggestedLags(item: Autocorrelation, unit: Unit): number[] {
  const lags = (item.suggested_lags ?? []).map((lag) => unit.seconds ? Math.round(lag.seconds / unit.seconds) : lag.observations);
  return [...new Set(lags.filter((lag) => lag >= 1))]
    .sort((one, other) => one - other).slice(0, MAX_LAGS);
}

/** A cycle as a lag in the step's unit, or undefined when it does not come out whole. */
export function cycleLag(seconds: number, observations: number, unit: Unit): number | undefined {
  const lag = unit.seconds ? Math.round(seconds / unit.seconds) : observations;
  return lag >= 1 ? lag : undefined;
}

/** Neighbouring chosen lags that move together, with the autocorrelation that says so. */
export function redundantPairs(lags: number[], item: Autocorrelation, unit: Unit) {
  const pairs: { one: number; other: number; correlation: number }[] = [];
  for (let index = 1; index < lags.length; index += 1) {
    const one = lags[index - 1]!, other = lags[index]!;
    const apart = unit.seconds ? Math.round((other - one) * unit.seconds / item.step_seconds) : other - one;
    const correlation = apart >= 1 ? item.acf[apart - 1] : undefined;
    if (correlation !== undefined && correlation >= REDUNDANT) pairs.push({ one, other, correlation });
  }
  return pairs;
}

/** A duration in its largest whole unit: 9 s, 14 min, 3.6 h, 7 d. */
export function duration(seconds: number) {
  if (seconds < 60) return `${Number(seconds.toPrecision(2))} s`;
  if (seconds < 3600) return `${Number((seconds / 60).toPrecision(2))} min`;
  if (seconds < 86400 * 2) return `${Number((seconds / 3600).toPrecision(2))} h`;
  return `${Number((seconds / 86400).toPrecision(2))} d`;
}
