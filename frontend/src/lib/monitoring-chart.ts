import type {
  MonitoringChartEvidence,
  MonitoringEvidenceCursor,
} from '@/types/monitoring';
import type { Alarm } from '@/types/charger';
import { compareTimestamps, epochMicroseconds, epochMilliseconds } from '@/lib/timestamps';

/** Keep alarm markers in the same monitor scope as the displayed detector result. */
export function filterServiceAnomalies(
  anomalies: readonly Alarm[],
  evidence: readonly MonitoringChartEvidence[],
  serviceId: string | undefined,
  readingId: string,
): Alarm[] {
  if (!serviceId) return [...anomalies];
  const times = new Set(evidence.filter(row => row.monitor_id === serviceId && row.alarm)
    .flatMap(row => [row.timestamp, row.input_timestamps[readingId]]
      .filter((time): time is string => time !== undefined).map(epochMicroseconds))
    .filter((time): time is bigint => time !== undefined));
  return anomalies.filter(item => {
    if (item.monitor_id) return item.monitor_id === serviceId;
    const time = epochMicroseconds(item.timestamp);
    return time !== undefined && times.has(time);
  });
}

export const getEvidenceTimeForSensor = (
  evidence: MonitoringChartEvidence,
  readingId: string,
): number | undefined => {
  const timestamp = evidence.input_timestamps[readingId];
  if (!timestamp) return undefined;
  const time = epochMilliseconds(timestamp);
  return Number.isFinite(time) ? time : undefined;
};

export const getMonitoringEvidenceCursor = (
  evidence: MonitoringChartEvidence[]
): MonitoringEvidenceCursor | undefined =>
  evidence.reduce<MonitoringEvidenceCursor | undefined>((latest, item) => {
    if (epochMicroseconds(item.created) === undefined || epochMicroseconds(item.timestamp) === undefined) return latest;
    const cursor = {
      created: item.created,
      timestamp: item.timestamp,
      monitor_id: item.monitor_id,
      sequence_number: item.sequence_number,
    };
    if (!latest) return cursor;
    const comparisons = [
      compareTimestamps(item.created, latest.created),
      compareTimestamps(item.timestamp, latest.timestamp),
      cursor.monitor_id === latest.monitor_id
        ? 0
        : cursor.monitor_id > latest.monitor_id ? 1 : -1,
      cursor.sequence_number - latest.sequence_number,
    ];
    return (comparisons.find((comparison) => comparison !== 0) ?? 0) > 0
      ? cursor
      : latest;
  }, undefined);

export function mergeMonitoringChartEvidence(
  current: MonitoringChartEvidence[],
  incoming: MonitoringChartEvidence[],
  limit = 2000
): MonitoringChartEvidence[] {
  if (incoming.length === 0) return current;

  const rows = new Map<string, MonitoringChartEvidence>();
  [...current, ...incoming].forEach((item) => {
    rows.set(
      `${item.timestamp}\u0000${item.monitor_id}\u0000${item.sequence_number}`,
      item
    );
  });

  return [...rows.values()]
    .sort((left, right) =>
      compareTimestamps(left.timestamp, right.timestamp) ||
      left.monitor_id.localeCompare(right.monitor_id) ||
      left.sequence_number - right.sequence_number
    )
    .slice(-limit);
}
