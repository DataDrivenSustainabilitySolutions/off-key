/** Local calendar arithmetic for time axes: day breaks and span-aware tick labels. */

type LocalParts = { year: number; month: number; day: number; hour: number; minute: number; second: number };

const partFormatters = new Map<string, Intl.DateTimeFormat>();
const localParts = (time: number, timeZone: string): LocalParts => {
  let formatter = partFormatters.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-US", { timeZone, hourCycle: "h23",
      year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" });
    partFormatters.set(timeZone, formatter);
  }
  const parts = Object.fromEntries(formatter.formatToParts(time)
    .filter(part => part.type !== "literal").map(part => [part.type, Number(part.value)]));
  return { year: parts.year!, month: parts.month!, day: parts.day!, hour: parts.hour! % 24, minute: parts.minute!, second: parts.second! };
};

/** Milliseconds the zone is ahead of UTC at this instant, to the second. */
const zoneOffset = (time: number, timeZone: string) => {
  const local = localParts(time, timeZone);
  const wall = Date.UTC(local.year, local.month - 1, local.day, local.hour, local.minute, local.second);
  return wall - Math.floor(time / 1000) * 1000;
};

/** The instant a local calendar day begins; Date.UTC normalises overflowing days. */
const startOfLocalDay = (year: number, month: number, day: number, timeZone: string) => {
  const wall = Date.UTC(year, month - 1, day);
  const guess = wall - zoneOffset(wall, timeZone);
  return wall - zoneOffset(guess, timeZone);
};

/** Each local midnight strictly after startMs and at or before endMs, up to `limit`. */
export function localMidnights(startMs: number, endMs: number, timeZone: string, limit = 62): number[] {
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return [];
  const { year, month, day } = localParts(startMs, timeZone);
  const midnights: number[] = [];
  for (let offset = 1; midnights.length <= limit; offset += 1) {
    const midnight = startOfLocalDay(year, month, day + offset, timeZone);
    if (midnight > endMs) return midnights;
    if (midnight > startMs) midnights.push(midnight);
  }
  // Too many to draw legibly; callers show none rather than a wall of lines.
  return [];
}

export const isLocalMidnight = (time: number, timeZone: string) => {
  const { hour, minute, second } = localParts(time, timeZone);
  return hour === 0 && minute === 0 && second === 0 && time % 1000 === 0;
};

const labelFormatters = new Map<string, (value: number) => string>();

/**
 * Tick labels that follow the visible span: seconds only within a few minutes,
 * hours and minutes beyond. A tick on a local midnight names its day instead,
 * styled through the axis label's `day` rich-text style.
 */
export function timeAxisLabelFormatter(timeZone: string, locale: string | undefined, spanMs: number,
  withDate = false): (value: number) => string {
  const seconds = spanMs <= 20 * 60_000;
  const key = `${timeZone}\u0000${locale ?? "\u0000"}\u0000${seconds}\u0000${withDate}`;
  const cached = labelFormatters.get(key);
  if (cached) return cached;
  const time = new Intl.DateTimeFormat(locale, { timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    ...(seconds ? { second: "2-digit" as const } : {}) });
  const date = new Intl.DateTimeFormat(locale, { timeZone, month: "short", day: "2-digit" });
  const day = new Intl.DateTimeFormat(locale, { timeZone, weekday: "short", month: "short", day: "numeric" });
  const formatter = (value: number) => {
    const instant = Number(value);
    if (isLocalMidnight(instant, timeZone)) return `{day|${day.format(instant)}}${withDate ? `\n${time.format(instant)}` : ""}`;
    return withDate ? `${date.format(instant)}\n${time.format(instant)}` : time.format(instant);
  };
  labelFormatters.set(key, formatter);
  return formatter;
}
