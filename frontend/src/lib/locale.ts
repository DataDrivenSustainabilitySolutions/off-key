/**
 * Every number, date and time on screen reads in English with a 24-hour clock,
 * whatever language the browser prefers. Lint keeps all formatting on LOCALE.
 */
export const LOCALE = "en";

/** A date and time formatter in LOCALE whose hours run from 00 to 23. */
export const dateTimeFormat = (options: Intl.DateTimeFormatOptions = {}): Intl.DateTimeFormat =>
  new Intl.DateTimeFormat(LOCALE, { ...options, hourCycle: "h23" });
