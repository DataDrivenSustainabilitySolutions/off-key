import type {
  MonitoringChartEvidence,
  MonitoringEvidenceCursor,
} from '@/types/monitoring';

export type MonitoringChartPoint = Record<string, unknown> & {
  time: number;
  timestamp: string;
};

export type MonitoringEvidenceSeries = {
  serviceId: string;
  dataKey: string;
  threshold: number;
};

export const martingaleDataKey = (serviceId: string): string =>
  `martingale:${serviceId}`;

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

export function buildMonitoringChartData<T extends { timestamp: string }>(
  telemetry: T[],
  evidence: MonitoringChartEvidence[]
): MonitoringChartPoint[] {
  const points = new Map<number, MonitoringChartPoint>();

  [...telemetry].reverse().forEach((item) => {
    const time = Date.parse(item.timestamp);
    if (!Number.isFinite(time)) return;
    points.set(time, { ...item, time, timestamp: item.timestamp });
  });

  evidence.forEach((item) => {
    const time = Date.parse(item.timestamp);
    if (!Number.isFinite(time)) return;
    const existing = points.get(time) ?? { time, timestamp: item.timestamp };
    points.set(time, {
      ...existing,
      [martingaleDataKey(item.service_id)]: item.restarted_martingale ?? undefined,
      [`alarm:${item.service_id}`]: item.alarm,
    });
  });

  return [...points.values()].sort((left, right) => left.time - right.time);
}

export function getMonitoringEvidenceSeries(
  evidence: MonitoringChartEvidence[]
): MonitoringEvidenceSeries[] {
  const series = new Map<string, MonitoringEvidenceSeries>();
  evidence.forEach((item) => {
    series.set(item.service_id, {
      serviceId: item.service_id,
      dataKey: martingaleDataKey(item.service_id),
      threshold: item.threshold,
    });
  });
  return [...series.values()];
}

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
