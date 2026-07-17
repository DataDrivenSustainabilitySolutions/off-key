import { describe, expect, it } from 'vitest';

import {
  buildMonitoringChartData,
  getMonitoringEvidenceSeries,
  martingaleDataKey,
} from '@/lib/monitoring-chart';
import type { MonitoringEvidence } from '@/types/monitoring';

const evidence = (
  serviceId: string,
  timestamp: string,
  martingale: number
): MonitoringEvidence => ({
  service_id: serviceId,
  timestamp,
  sequence_number: 1,
  charger_id: 'charger-1',
  sensor_set: ['L1'],
  p_value: 0.5,
  e_value: 1,
  e_value_is_infinite: false,
  log_e_value: 0,
  restarted_martingale: martingale,
  restarted_martingale_is_infinite: false,
  log_restarted_martingale: Math.log(martingale),
  threshold: 100,
  alarm: false,
});

describe('monitoring chart adapter', () => {
  it('keeps separate martingale keys for successive service runs', () => {
    const rows = buildMonitoringChartData(
      [{ timestamp: '2026-01-01T00:00:00Z', value: 12 }],
      [
        evidence('service-a', '2026-01-01T00:00:01Z', 4),
        evidence('service-b', '2026-01-01T00:00:02Z', 2),
      ]
    );

    expect(rows[1][martingaleDataKey('service-a')]).toBe(4);
    expect(rows[1][martingaleDataKey('service-b')]).toBeUndefined();
    expect(rows[2][martingaleDataKey('service-b')]).toBe(2);
    expect(getMonitoringEvidenceSeries([
      evidence('service-a', '2026-01-01T00:00:01Z', 4),
      evidence('service-b', '2026-01-01T00:00:02Z', 2),
    ])).toHaveLength(2);
  });

  it('sorts telemetry and evidence on a numeric time axis', () => {
    const rows = buildMonitoringChartData(
      [{ timestamp: '2026-01-01T00:00:02Z', value: 12 }],
      [evidence('service-a', '2026-01-01T00:00:01Z', 4)]
    );

    expect(rows.map((row) => row.time)).toEqual([...rows.map((row) => row.time)].sort());
  });
});
