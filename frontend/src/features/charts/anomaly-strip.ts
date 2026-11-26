/** One monitor's anomalies on the strip, in its own colour. */
export type StripRow = { id: string; name: string; color: string; spans: ReadonlyArray<readonly [number, number]> };
/** Neighbouring stretches that several monitors share: under the lens it shows each monitor once, all the same size. */
export type StripOverlap = { a: number; b: number; members: StripRow[] };
type StripPart = { a: number; b: number; members: StripRow[]; overlap?: StripOverlap };
/** Anomalies that touch, whoever raised them, drawn as one rounded shape. */
export type StripPill = { left: number; right: number; parts: StripPart[] };
export type StripLens = { focus: number; strength: number; lock?: StripOverlap };

export const STRIP = { height: 12, minHalf: 7, stripe: 4, power: 3.1, grow: 9, field: 22 } as const;

/** Lays every monitor's anomalies on one line of the given width, in pixels. */
export function buildStripPills(rows: readonly StripRow[], domain: readonly [number, number], width: number): StripPill[] {
  const span = domain[1] - domain[0];
  if (!(span > 0) || !(width > 0)) return [];
  const place = (time: number) => Math.max(0, Math.min(width, (time - domain[0]) / span * width));
  const covered = rows.map(row => row.spans.filter(([start, end]) => end >= domain[0] && start <= domain[1])
    .map(([start, end]) => [place(start) - STRIP.minHalf, place(end) + STRIP.minHalf] as const));
  const edges = [...new Set(covered.flat().flat())].sort((left, right) => left - right);
  const pills: StripPill[] = [];
  let pill: StripPill | undefined;
  for (let index = 0; index < edges.length - 1; index++) {
    const a = edges[index]!, b = edges[index + 1]!, middle = (a + b) / 2;
    const members = rows.filter((_, row) => covered[row]!.some(([start, end]) => start <= middle && middle <= end));
    if (!members.length) { pill = undefined; continue; }
    if (!pill) pills.push(pill = { left: a, right: b, parts: [] });
    const last = pill.parts[pill.parts.length - 1];
    if (last && last.members.length === members.length && last.members.every((member, at) => member === members[at])) last.b = b;
    else pill.parts.push({ a, b, members });
    pill.right = b;
  }
  for (const { parts } of pills) {
    let overlap: StripOverlap | undefined;
    for (const part of parts) {
      if (part.members.length < 2) { overlap = undefined; continue; }
      const shared: StripOverlap = overlap ??= { a: part.a, b: part.b, members: [] };
      shared.b = part.b;
      shared.members = rows.filter(row => shared.members.includes(row) || part.members.includes(row));
      part.overlap = shared;
    }
  }
  return pills;
}

/** The lens at one instant: a fisheye along the strip. Drawing and hit-testing both use it,
 * so what is pressed is what is seen. */
export function lensOptics(lens: StripLens, width: number) {
  const strength = Math.max(0, lens.strength), reach = Math.max(44, Math.min(70, width * 0.11));
  let power: number = STRIP.power;
  // Over a shared stretch the lens rests on its middle, strong enough for every field to be wide enough to press.
  if (lens.lock) {
    const half = (lens.lock.b - lens.lock.a) / 2, want = Math.min(reach * 0.8, lens.lock.members.length * STRIP.field / 2);
    if (want > half) power = Math.max(power, (half - want) / (half / reach * (want - reach)));
  }
  const gain = strength * power;
  const fish = (x: number) => {
    const distance = x - lens.focus, t = Math.abs(distance) / reach;
    return t >= 1 || !gain ? x : lens.focus + Math.sign(distance) * reach * ((gain + 1) * t) / (gain * t + 1);
  };
  const bump = (x: number) => {
    const t = Math.abs(x - lens.focus) / reach;
    return t >= 1 ? 0 : strength * (1 - t * t) ** 2;
  };
  return { fish, bump };
}

/** What lies under the pointer, measured at the positions the strip is drawn at. */
export function locateOnStrip(pills: readonly StripPill[], lens: StripLens, width: number, at: number):
{ lock?: StripOverlap; row?: StripRow; slice: number } {
  const { fish } = lensOptics(lens, width);
  const over = (part: { a: number; b: number }, slack: number) => at >= fish(part.a) - slack && at <= fish(part.b) + slack;
  const part = pills.flatMap(pill => pill.parts).find(candidate => over(candidate, 0));
  const lock = lens.lock && over(lens.lock, 3) ? lens.lock : part?.overlap;
  if (!lock) return { row: part?.members[0], slice: 0 };
  const rested = lensOptics({ ...lens, lock }, width).fish, a = rested(lock.a), b = rested(lock.b), count = lock.members.length;
  const slice = Math.max(0, Math.min(count - 1, Math.floor((at - a) / ((b - a) / count))));
  return { lock, row: lock.members[slice], slice };
}

/** Consecutive alarming results are one anomaly, ended by the next quiet result. */
export function alarmSpans(results: ReadonlyArray<{ time: number; alarm: boolean }>): Array<[number, number]> {
  const spans: Array<[number, number]> = [];
  let open: [number, number] | undefined;
  for (const { time, alarm } of [...results].sort((left, right) => left.time - right.time)) {
    if (!alarm) open = undefined;
    else if (open) open[1] = time;
    else spans.push(open = [time, time]);
  }
  return spans;
}
