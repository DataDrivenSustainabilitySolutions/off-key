import { CircleCheck } from "lucide-react";
import type { CollectionPolicy, SensorActivity } from "@/types/collection";

export function SensorActivityBadge({
  activity,
  policy,
  available,
  now,
}: {
  activity?: SensorActivity;
  policy?: CollectionPolicy;
  available: boolean;
  now: number;
}) {
  const received = activity ? Date.parse(activity.received_at) : NaN;
  const windowSeconds =
    policy?.mode === "sample" ? Math.max(60, policy.interval_seconds * 3) : 60;
  const age = now - received;
  const recent =
    !!policy && policy.mode !== "off" && available && !activity?.is_snapshot &&
    age >= 0 && age <= windowSeconds * 1000;
  let label = "No data yet";
  if (!policy) label = "Save to observe";
  else if (policy.mode === "off") label = "Collection off";
  else if (!available) label = "Status unavailable";
  else if (Number.isFinite(received)) {
    if (activity?.is_snapshot) label = "Retained snapshot";
    else label = recent ? "Recent data" : "No recent data";
  }

  return (
    <div className="ml-2 mt-1 flex basis-full flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      <span
        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium ${
          recent
            ? "border-emerald-600/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
            : "border-border bg-muted/40 text-muted-foreground"
        }`}
      >
        {recent && <CircleCheck className="size-3.5" aria-hidden="true" />}
        {label}
      </span>
      {activity && Number.isFinite(received) && (
        <time dateTime={activity.received_at} className="text-muted-foreground">
          Last received {new Date(received).toLocaleString()}
        </time>
      )}
    </div>
  );
}
