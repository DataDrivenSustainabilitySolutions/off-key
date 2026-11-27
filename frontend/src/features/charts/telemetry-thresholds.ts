export interface DetectionValueBounds {
  minimum: number;
  maximum: number;
}

export type DetectionTimeValue = [timeMs: number, value: number | null];

const expandCollapsedRange = (range: { fromMs?: number; toMs?: number }) =>
  range.fromMs !== undefined && range.fromMs === range.toMs
    ? { fromMs: range.fromMs - 500, toMs: range.fromMs + 500 }
    : range;

const positivePowerOfTen = (exponent: number): number =>
  Math.max(Number.MIN_VALUE, Math.min(Number.MAX_VALUE, 10 ** exponent));

/** Compute padding in the displayed score space, without letting x-axis zoom rescale it. */
export const getDetectionValueBounds = (
  scale: "log" | "linear",
  scores: readonly DetectionTimeValue[],
  thresholds: readonly DetectionTimeValue[],
): DetectionValueBounds => {
  const values = [...scores, ...thresholds]
    .flatMap(([, value]) => value !== null && Number.isFinite(value) ? [value] : [])
    .filter((value) => scale === "linear" || value > 0);
  if (scale === "log") {
    const logs = [0, ...values.map((value) => Math.log10(value))];
    const minimum = Math.min(...logs);
    const maximum = Math.max(...logs);
    const span = maximum - minimum;
    return {
      minimum: positivePowerOfTen(minimum - span * 0.05),
      maximum: positivePowerOfTen(maximum + Math.max(0.25, span * 0.1)),
    };
  }
  const minimum = values.length ? Math.min(...values) : 0;
  const maximum = values.length ? Math.max(...values) : 1;
  const span = maximum - minimum || 0.1 * Math.max(Math.abs(maximum), 1);
  // Subtraction can overflow for finite scores near opposite float limits.
  const paddingSpan = Number.isFinite(span) ? span : Number.MAX_VALUE;
  return {
    minimum: Math.max(-Number.MAX_VALUE, minimum - paddingSpan * 0.05),
    maximum: Math.min(Number.MAX_VALUE, maximum + paddingSpan * 0.15),
  };
};

export const getChartDomain = (
  extent: readonly [number, number] | undefined,
  range: { fromMs?: number; toMs?: number } = {},
): [number, number] | undefined => {
  if (!extent) return undefined;
  const [start, end] = extent;
  const singleton = start === end;
  const visibleRange = expandCollapsedRange(range);
  return [
    visibleRange.fromMs ?? (singleton ? start - 500 : start),
    visibleRange.toMs ?? (singleton ? end + 500 : end),
  ];
};
