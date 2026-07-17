import type { MonitoringEvidence } from '@/types/monitoring';

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

export function buildMonitoringChartData<T extends { timestamp: string }>(
  telemetry: T[],
  evidence: MonitoringEvidence[]
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
  evidence: MonitoringEvidence[]
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
