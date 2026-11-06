import type {
  MonitoringChartEvidence,
  MonitoringEvidenceCursor,
} from '@/types/monitoring';
import type { Alarm } from '@/types/charger';

/** Keep alarm markers in the same monitor scope as the displayed detector result. */
export function filterServiceAnomalies(
  anomalies: readonly Alarm[],
  evidence: readonly MonitoringChartEvidence[],
  serviceId: string | undefined,
  readingId: string,
): Alarm[] {
  if (!serviceId) return [...anomalies];
  const times = new Set(evidence.filter(row => row.monitor_id === serviceId && row.alarm)
    .flatMap(row => [Date.parse(row.timestamp), getEvidenceTimeForSensor(row, readingId)]));
  return anomalies.filter(item => item.monitor_id ? item.monitor_id === serviceId : times.has(Date.parse(item.timestamp)));
}

export const getEvidenceTimeForSensor = (
  evidence: MonitoringChartEvidence,
  readingId: string,
): number | undefined => {
  const timestamp = evidence.input_timestamps[readingId];
  if (!timestamp) return undefined;
  const time = Date.parse(timestamp);
  return Number.isFinite(time) ? time : undefined;
};

export const getMonitoringEvidenceCursor = (
  evidence: MonitoringChartEvidence[]
): MonitoringEvidenceCursor | undefined =>
  evidence.reduce<MonitoringEvidenceCursor | undefined>((latest, item) => {
    const createdTime = Date.parse(item.created);
    const eventTime = Date.parse(item.timestamp);
    if (!Number.isFinite(createdTime) || !Number.isFinite(eventTime)) return latest;
    const cursor = {
      created: item.created,
      timestamp: item.timestamp,
      monitor_id: item.monitor_id,
      sequence_number: item.sequence_number,
    };
    if (!latest) return cursor;
    const comparisons = [
      createdTime - Date.parse(latest.created),
      eventTime - Date.parse(latest.timestamp),
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
    .map((item) => ({ item, time: Date.parse(item.timestamp) }))
    .sort((left, right) =>
      left.time - right.time ||
      left.item.monitor_id.localeCompare(right.item.monitor_id) ||
      left.item.sequence_number - right.item.sequence_number
    )
    .slice(-limit)
    .map(({ item }) => item);
}
