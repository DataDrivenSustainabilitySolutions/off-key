import { describe, expect, it } from 'vitest';

import {
  buildMonitoringChartData,
  getMonitoringEvidenceCursor,
  getMonitoringEvidenceSeries,
  martingaleDataKey,
  mergeMonitoringChartEvidence,
} from '@/lib/monitoring-chart';
import type { MonitoringEvidence } from '@/types/monitoring';

const evidence = (
  serviceId: string,
  timestamp: string,
  martingale: number
): MonitoringEvidence & { created: string } => ({
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
  created: timestamp,
});

describe('monitoring chart adapter', () => {
  it('advances evidence cursors by ingestion order', () => {
    const olderEvent = {
      ...evidence('service-b', '2026-01-01T00:00:01Z', 2),
      created: '2026-01-01T00:01:00Z',
    };
    const newerEvent = {
      ...evidence('service-a', '2026-01-01T00:00:02Z', 3),
      created: '2026-01-01T00:00:30Z',
    };

    expect(getMonitoringEvidenceCursor([olderEvent, newerEvent])).toEqual({
      created: olderEvent.created,
      timestamp: olderEvent.timestamp,
      service_id: olderEvent.service_id,
      sequence_number: olderEvent.sequence_number,
    });
  });

  it.each(['created', 'timestamp'] as const)(
    'skips evidence with an invalid %s cursor field',
    (field) => {
      const valid = evidence('service-a', '2026-01-01T00:00:01Z', 2);
      const invalid = { ...valid, [field]: 'not-a-date' };

      expect(getMonitoringEvidenceCursor([invalid, valid])).toEqual({
        created: valid.created,
        timestamp: valid.timestamp,
        service_id: valid.service_id,
        sequence_number: valid.sequence_number,
      });
    }
  );

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

  it('merges incremental evidence by composite identity and caps the window', () => {
    const first = evidence('service-a', '2026-01-01T00:00:01Z', 1);
    const second = { ...evidence('service-a', '2026-01-01T00:00:02Z', 2), sequence_number: 2 };
    const duplicate = { ...second, restarted_martingale: 3 };

    const rows = mergeMonitoringChartEvidence([first, second], [duplicate], 2);

    expect(rows).toHaveLength(2);
    expect(rows[1]?.restarted_martingale).toBe(3);
    expect(mergeMonitoringChartEvidence(rows, [])).toBe(rows);
  });
});
