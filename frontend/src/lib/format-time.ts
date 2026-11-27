/**
 * Recent activity uses relative time and falls back to a short date after a
 * day. Reading freshness uses elapsed time even for older observations.
 */

import { dateTimeFormat, LOCALE } from "@/lib/locale";

const DAY_MS = 86_400_000;
const dateTime = dateTimeFormat({ dateStyle: "medium", timeStyle: "short" });
const exactDateTime = dateTimeFormat({ dateStyle: "medium", timeStyle: "medium" });
const timeOfDay = dateTimeFormat({ timeStyle: "short" });
const relative = new Intl.RelativeTimeFormat(LOCALE, { numeric: "auto" });
const elapsedDays = new Intl.RelativeTimeFormat(LOCALE, { numeric: "always" });

export type RelativeTimeMode = "recent" | "elapsed";

export function parseTime(value: string | number | Date | null | undefined): Date | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isFinite(date.getTime()) ? date : undefined;
}

/** "Oct 21, 2026, 18:37" */
export const formatDateTime = (value: string | number | Date) => {
  const date = parseTime(value);
  return date ? dateTime.format(date) : "";
};

/** "Oct 21, 2026, 18:37:29", for tooltips and places that need seconds. */
export const formatExactDateTime = (value: string | number | Date) => {
  const date = parseTime(value);
  return date ? exactDateTime.format(date) : "";
};

/** "18:37", for rows that already sit under a day heading. */
export const formatTimeOfDay = (value: string | number | Date) => {
  const date = parseTime(value);
  return date ? timeOfDay.format(date) : "";
};

/** Recent times use minutes and hours. Elapsed times include seconds and days. */
export function formatRelativeTime(value: string | number | Date, now = Date.now(), mode: RelativeTimeMode = "recent") {
  const date = parseTime(value);
  if (!date) return "";
  const elapsed = now - date.getTime();
  const showElapsed = mode === "elapsed";
  if (elapsed < -60_000) return dateTime.format(date);
  if (elapsed >= DAY_MS) return showElapsed
    ? elapsedDays.format(-Math.floor(elapsed / DAY_MS), "day") : dateTime.format(date);
  const seconds = showElapsed ? Math.floor(elapsed / 1000) : Math.round(elapsed / 1000);
  if (seconds < 60) return showElapsed && seconds > 0 ? relative.format(-seconds, "second") : "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return relative.format(-minutes, "minute");
  return relative.format(-Math.floor(minutes / 60), "hour");
}

const startOfDay = (time: number) => {
  const date = new Date(time);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
};

/** "Today", "Yesterday", or "Monday, October 19" (with the year when it differs). */
export function formatDay(value: string | number | Date, now = Date.now()) {
  const date = parseTime(value);
  if (!date) return "";
  const days = Math.round((startOfDay(now) - startOfDay(date.getTime())) / DAY_MS);
  if (days === 0 || days === 1) return relative.format(-days, "day").replace(/^./, letter => letter.toLocaleUpperCase());
  return dateTimeFormat({ weekday: "long", month: "long", day: "numeric",
    ...(date.getFullYear() !== new Date(now).getFullYear() ? { year: "numeric" } : {}) }).format(date);
}

/** A stable key for grouping times by local calendar day. */
export function dayKey(value: string | number | Date) {
  const date = parseTime(value);
  return date ? `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}` : "";
}
