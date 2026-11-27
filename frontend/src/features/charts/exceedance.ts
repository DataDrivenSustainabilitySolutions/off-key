/** One plotted value, how far it lies past a limit (negative inside it), and which kind of excursion it belongs to. */
export type MarginSample = { time: number; value: number | null; margin: number | null; kind?: string };
export type LinePoint = [time: number, value: number | null];

const across = (from: MarginSample, to: MarginSample): LinePoint => {
  const share = from.margin! / (from.margin! - to.margin!);
  return [from.time + (to.time - from.time) * share, from.value! + (to.value! - from.value!) * share];
};

/**
 * The stretches of a line that lie past a limit, one line per kind, each starting and ending
 * exactly where the line crosses the limit. Drawn over the full line, an excursion reads as the
 * line itself changing colour, instead of a dot on every value outside.
 */
export function excursions(samples: readonly MarginSample[], kinds: readonly string[]): Record<string, LinePoint[]> {
  const lines: Record<string, LinePoint[]> = Object.fromEntries(kinds.map(kind => [kind, []]));
  const kindOf = (sample?: MarginSample) =>
    sample && sample.value !== null && sample.margin !== null && sample.margin >= 0 ? sample.kind ?? kinds[0] : undefined;
  const inside = (sample?: MarginSample) => sample !== undefined && sample.value !== null && sample.margin !== null && sample.margin < 0;
  samples.forEach((sample, index) => {
    const kind = kindOf(sample);
    if (!kind) return;
    const line = lines[kind]!;
    const before = samples[index - 1], after = samples[index + 1];
    if (kindOf(before) !== kind) {
      if (inside(before)) line.push(across(before!, sample));
      // Where one kind of excursion turns into another, both share the point between them.
      else if (kindOf(before)) line.push([before!.time, before!.value]);
    }
    line.push([sample.time, sample.value]);
    if (kindOf(after) !== kind) {
      if (inside(after)) line.push(across(sample, after!));
      line.push([after?.time ?? sample.time, null]);
    }
  });
  return lines;
}
