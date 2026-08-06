import type {
  MonitoringChartEvidence,
  MonitoringEvidenceCursor,
} from '@/types/monitoring';

export const getEvidenceTimeForSensor = (
  evidence: MonitoringChartEvidence,
  sensor: string,
): number | undefined => {
  const timestamp = evidence.input_timestamps[sensor];
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
      service_id: item.service_id,
      sequence_number: item.sequence_number,
    };
    if (!latest) return cursor;
    const comparisons = [
      createdTime - Date.parse(latest.created),
      eventTime - Date.parse(latest.timestamp),
      cursor.service_id === latest.service_id
        ? 0
        : cursor.service_id > latest.service_id ? 1 : -1,
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
      `${item.timestamp}\u0000${item.service_id}\u0000${item.sequence_number}`,
      item
    );
  });

  return [...rows.values()]
    .sort((left, right) =>
      Date.parse(left.timestamp) - Date.parse(right.timestamp) ||
      left.service_id.localeCompare(right.service_id) ||
      left.sequence_number - right.sequence_number
    )
    .slice(-limit);
}
