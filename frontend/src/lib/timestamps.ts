/** PostgreSQL observation identities have microsecond precision; Date truncates it. */
export function epochMicroseconds(timestamp: string): bigint | undefined {
  const milliseconds = Date.parse(timestamp);
  if (!Number.isFinite(milliseconds)) return undefined;
  const fraction = /[T ]\d{2}:\d{2}:\d{2}\.(\d+)/.exec(timestamp)?.[1] ?? "";
  const remainder = fraction.padEnd(6, "0").slice(3, 6);
  return BigInt(milliseconds) * 1000n + BigInt(remainder);
}

/** Charts use numeric milliseconds, including the submillisecond fraction. */
export function epochMilliseconds(timestamp: string): number {
  const time = epochMicroseconds(timestamp);
  return time === undefined ? NaN : Number(time) / 1000;
}

/** Preserve chart-time precision when preview samples join recorded history. */
export function isoTimestamp(milliseconds: number): string {
  const whole = Math.floor(milliseconds);
  const micros = Math.round((milliseconds - whole) * 1000);
  if (micros === 1000) return new Date(whole + 1).toISOString();
  const iso = new Date(whole).toISOString();
  return micros ? iso.replace(/Z$/, `${String(micros).padStart(3, "0")}Z`) : iso;
}

export function compareTimestamps(left: string, right: string): number {
  const a = epochMicroseconds(left), b = epochMicroseconds(right);
  if (a === undefined || b === undefined) return NaN;
  return a === b ? 0 : a < b ? -1 : 1;
}
