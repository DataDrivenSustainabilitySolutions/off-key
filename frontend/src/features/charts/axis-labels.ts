/**
 * Value-axis tick labels: short enough for a narrow gutter, exact enough that two
 * ticks never read the same, and a gutter that fits the widest label drawn.
 */

import { LOCALE } from "@/lib/locale";

const numberFormatters = new Map<string, Intl.NumberFormat>();

const numberFormatter = (compact: boolean, significantDigits: number): Intl.NumberFormat => {
  const key = `${compact}\u0000${significantDigits}`;
  const cached = numberFormatters.get(key);
  if (cached) return cached;
  const formatter = new Intl.NumberFormat(LOCALE, {
    notation: compact ? "compact" : "standard", maximumSignificantDigits: significantDigits });
  numberFormatters.set(key, formatter);
  return formatter;
};

/** Below this, an axis writes its values out in full: 99,500 reads better than 99.5K and still fits. */
const COMPACT_FROM = 100_000;

/** Whether an axis showing these values abbreviates them. One choice per axis, so its labels read alike. */
export const compactAxis = (values: Iterable<number | null | undefined>): boolean => {
  for (const value of values) if (value !== null && value !== undefined && Math.abs(value) >= COMPACT_FROM) return true;
  return false;
};

/** The digits a value needs to be written exactly, after float noise such as 0.30000000000000004. */
const significantDigits = (value: number): number =>
  value.toExponential(11).split("e")[0]!.replace(/^-/, "").replace(".", "").replace(/0+$/, "").length || 1;

/**
 * A tick value for a value axis, in English: in full, such as 10,120 or 0.0025,
 * or on a compact axis abbreviated, such as 5.01M. Ticks are round numbers, so every digit
 * a tick has is kept: neighbours such as 5,010,000 and 5,020,000 stay 5.01M and 5.02M
 * rather than collapsing into one label.
 */
export const formatAxisValue = (value: number, compact = true): string => {
  if (!Number.isFinite(value)) return String(value);
  const rounded = Number(value.toPrecision(12));
  if (rounded === 0) return "0";
  const magnitude = Math.abs(rounded);
  // Beyond what compact names, or so small that zeros would fill the gutter.
  if (magnitude >= 1e15 || magnitude < 1e-4) return rounded.toExponential().replace("e+", "e");
  return numberFormatter(compact, significantDigits(rounded)).format(rounded);
};

/** Room between the plot and its value labels: ECharts' axisLabel.margin. */
const LABEL_MARGIN = 8;
/** Room between the chart's edge and the start of the widest label. */
const EDGE_PADDING = 6;
/** The gutter grows in steps, so a live axis does not shift on every new tick. */
const GUTTER_STEP = 8;
const MINIMUM_GUTTER = 32;

/** The left gutter that shows the widest value label whole, shared by every pane so their times line up. */
export const valueAxisGutter = (labelWidths: readonly number[]): number => {
  const widest = Math.max(0, ...labelWidths);
  const needed = Math.ceil((widest + LABEL_MARGIN + EDGE_PADDING) / GUTTER_STEP) * GUTTER_STEP;
  return Math.max(MINIMUM_GUTTER, needed);
};
