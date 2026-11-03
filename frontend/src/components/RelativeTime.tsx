import { formatExactDateTime, formatRelativeTime, parseTime, type RelativeTimeMode } from "@/lib/format-time";
import { useNow } from "@/hooks/use-now";

type Props = { value: string | number | Date | null | undefined; fallback?: string; className?: string; mode?: RelativeTimeMode };

/** A time that reads relative, with the exact time on hover. */
export function RelativeTime({ value, fallback = "", className, mode = "recent" }: Props) {
  const date = parseTime(value);
  const now = useNow(mode === "elapsed" ? 1_000 : 15_000, !!date);
  if (!date) return <>{fallback}</>;
  return <time className={className} dateTime={date.toISOString()} title={formatExactDateTime(date)}>
    {formatRelativeTime(date, now, mode)}
  </time>;
}
