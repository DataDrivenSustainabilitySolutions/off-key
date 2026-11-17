import type { ActiveService, MonitoringChartEvidence } from "@/types/monitoring";

export const DAY = 86_400_000;

/** When the shadow run began: its latest start, or the service's creation. */
export function shadowSince(service: ActiveService): string | undefined {
  const starts = (service.origin?.history ?? []).filter(record => record.event === "started");
  return starts[starts.length - 1]?.at ?? service.created_at ?? undefined;
}

/**
 * Alarms since a time, and the episodes they form: observations in a row of one monitor raise one
 * alarm for a reader, however many of them alarmed.
 */
export function mutedAlarms(rows: Pick<MonitoringChartEvidence, "timestamp" | "sequence_number" | "alarm">[], since?: string) {
  const from = since ? Date.parse(since) : -Infinity;
  const kept = rows.filter(row => row.alarm && Date.parse(row.timestamp) >= from)
    .map(row => row.sequence_number).sort((a, b) => a - b);
  let episodes = 0;
  kept.forEach((sequence, index) => { if (index === 0 || sequence !== kept[index - 1]! + 1) episodes += 1; });
  return { observations: kept.length, episodes };
}
