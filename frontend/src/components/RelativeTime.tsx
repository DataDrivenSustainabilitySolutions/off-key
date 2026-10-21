import { formatExactDateTime, formatRelativeTime, parseTime } from "@/lib/format-time";
import { useNow } from "@/hooks/use-now";

type Props = { value: string | number | Date | null | undefined; fallback?: string; className?: string };

/** A time that reads relative, with the exact time on hover. */
export function RelativeTime({ value, fallback = "", className }: Props) {
  const now = useNow();
  const date = parseTime(value);
  if (!date) return <>{fallback}</>;
  return <time className={className} dateTime={date.toISOString()} title={formatExactDateTime(date)}>
    {formatRelativeTime(date, now)}
  </time>;
}
