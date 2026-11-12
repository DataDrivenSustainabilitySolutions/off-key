import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Reporting from '@/pages/Anomalies';
import Details from '@/pages/Details';
import AnomalyInvestigation from '@/features/reporting/AnomalyInvestigation';
import { anomalyDescription, anomalyTriggers, compactRecency } from '@/features/reporting/model';
import { getEventReadings } from '@/features/reporting/readings';
import { buildNavigationIndex } from '@/domain/system/navigationIndex';
import { createEmptySystem } from '@/domain/system/systemDocument';
import type { ChartNavigationState } from '@/features/charts/telemetry-chart';
import type { Alarm, AlarmPage } from '@/types/charger';
import type { SystemDocument } from '@/types/system';
import { deleteAlarmSelection, getAlarm, getTelemetryRange, previewAlarmDeletion, queryAlarms } from '@/lib/charger-api';
import { API_CONFIG } from '@/lib/api-config';
import { epochMilliseconds } from '@/lib/timestamps';
import { alarm, chartEvidence, trackerResult } from './support/fixtures/monitoring';
import { mqttConnection } from './support/fixtures/system';

vi.mock('@/lib/charger-api', () => ({
  queryAlarms: vi.fn(), getAlarm: vi.fn(), getTelemetryRange: vi.fn(),
  previewAlarmDeletion: vi.fn(), deleteAlarmSelection: vi.fn(),
}));
vi.mock('@/auth/AuthContext', () => ({ useAuth: () => ({ can: () => canDelete }) }));
vi.mock('@/features/workspace/catalogue-context', () => ({ useCatalogue: () => catalogue }));
vi.mock('@/features/charts/DynamicTelemetryChart', () => ({ default: (props: {
  telemetryData: { type: string }; anomalies: Alarm[]; navigationState: ChartNavigationState;
  onNavigationStateChange: (id: string, state: ChartNavigationState) => void;
}) => <section aria-label={`Chart ${props.telemetryData.type}`}>
  <output>{JSON.stringify({ navigation: props.navigationState, events: props.anomalies.map(item => item.alarm_id) })}</output>
  <button onClick={() => props.onNavigationStateChange(props.telemetryData.type, {
    range: { fromMs: Date.parse('2026-10-10T12:00:00Z'), toMs: Date.parse('2026-10-10T13:00:00Z') },
    viewport: { mode: 'absolute', startMs: Date.parse('2026-10-10T12:00:00Z'), endMs: Date.parse('2026-10-10T13:00:00Z') },
  })}>Change time range</button>
</section> }));

const document: SystemDocument = { ...createEmptySystem(),
  brokers: [mqttConnection({ id: 'broker', label: 'Site', host: 'localhost' })],
  devices: [{ id: 'charger', label: 'Charger 1', kind: 'charger', broker_id: 'broker' }],
  readings: ['temperature', 'current'].map(id => ({ id, label: id === 'temperature' ? 'Temperature' : 'Current',
    broker_id: 'broker', device_id: 'charger', topic: id, value_type: 'number', category: 'Electrical' })),
};
const catalogue = { system: { snapshot: { document }, refresh: vi.fn(), error: undefined },
  index: buildNavigationIndex(document), streamIds: undefined, selected: undefined, selectionMissing: false };
let canDelete = true;
const at = '2026-10-10T12:30:00.000Z';
const first = alarm({ alarm_id: 'one', timestamp: at, device_id: 'charger', reading_ids: ['temperature', 'current'],
  reading_labels: { temperature: 'Temperature', current: 'Current' }, multivariate: true,
  alarm_type: 'ml_conformal_static_multivariate', monitor_id: 'monitor-a', value_type: 'conformal_pvalue', value: 0.000032 });
const second = alarm({ ...first, alarm_id: 'two', timestamp: '2026-10-10T12:20:00.000Z',
  alarm_type: 'ml_adaptive_stream_multivariate', value_type: 'anomaly_score', value: 0.23 });
const evidence = chartEvidence({ monitor_id: 'monitor-a', timestamp: at,
  reading_ids: first.reading_ids, input_timestamps: { temperature: at, current: '2026-10-10T12:29:58.000Z' },
  strategy: 'static_baseline', alarm: true, tracker_results: [trackerResult({ alarm_fired: true, statistic_value: 120 })],
});
const page = (items = [first, second], count = items.length, next: AlarmPage['next'] = null): AlarmPage => ({
  items, summary: { count, devices: count ? 1 : 0, latest: items[0]?.timestamp ?? null }, next, unknown_reading_ids: [],
  readings: document.readings.map(reading => ({ reading_id: reading.id, label: reading.label, device_id: 'charger', device_label: 'Charger 1', count })),
});
function mount(path = '/anomalies') {
  const router = createMemoryRouter([
    { path: '/anomalies', element: <Reporting /> },
    { path: '/anomalies/:alarmId', element: <AnomalyInvestigation /> },
    { path: '/details/:deviceId', element: <Details /> },
  ], { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}
const loaded = () => screen.findByRole('link', { name: 'Evidence threshold crossed' });
const rowCheckboxes = () => screen.getAllByRole('checkbox', { name: /^Select Charger/ });

beforeEach(() => {
  vi.clearAllMocks(); canDelete = true;
  vi.mocked(queryAlarms).mockImplementation(async () => page());
  vi.mocked(getAlarm).mockResolvedValue({ alarm: first, evidence });
  vi.mocked(getTelemetryRange).mockResolvedValue([{ timestamp: at, value: 23 }]);
  vi.mocked(previewAlarmDeletion).mockResolvedValue({ token: 'frozen', count: 2, expires_at: new Date(Date.now() + 600_000).toISOString() });
  vi.mocked(deleteAlarmSelection).mockResolvedValue({ count: 2 });
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
});

describe('reporting selection', () => {
  it('selects all pages with exclusions and requires the reviewed confirmation', async () => {
    vi.mocked(queryAlarms).mockResolvedValue(page([first, second], 4, { timestamp: second.timestamp, alarm_id: second.alarm_id }));
    vi.mocked(previewAlarmDeletion).mockResolvedValue({ token: 'frozen', count: 3, expires_at: new Date(Date.now() + 600_000).toISOString() });
    mount('/anomalies?range=7d&p=0.001'); await loaded();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select all loaded anomalies' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select all 4 matching events' }));
    fireEvent.click(rowCheckboxes()[0]!);
    expect(screen.getByText('3 selected across all pages')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Delete selected' }));
    const dialog = await screen.findByRole('dialog', { name: 'Delete 3 anomalies?' });
    expect(previewAlarmDeletion).toHaveBeenCalledWith({ query: vi.mocked(queryAlarms).mock.calls[0]![0], exclude_ids: ['one'] });
    expect(vi.mocked(queryAlarms).mock.calls[0]![0]).toMatchObject({ max_p_value: 0.001, since: expect.any(String), limit: 500 });
    expect(dialog.textContent).toContain('All sources · Last 7 days · p ≤ 0.001');
    expect(deleteAlarmSelection).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(deleteAlarmSelection).not.toHaveBeenCalled();
    expect(screen.getByText('3 selected across all pages')).toBeTruthy();
  });

  it('keeps explicit selections across pages, retries errors and refreshes after deleting', async () => {
    vi.mocked(queryAlarms).mockImplementation(async query => query.before ? page([second])
      : page([first], 2, { timestamp: first.timestamp, alarm_id: first.alarm_id }));
    mount(); await loaded(); fireEvent.click(rowCheckboxes()[0]!);
    fireEvent.click(screen.getByRole('button', { name: 'Load older events (1 more)' }));
    await screen.findByRole('link', { name: 'Adaptive threshold exceeded' });
    fireEvent.click(rowCheckboxes()[1]!);
    fireEvent.click(screen.getByRole('button', { name: 'Delete selected' }));
    let dialog = await screen.findByRole('dialog', { name: 'Delete 2 anomalies?' });
    expect(previewAlarmDeletion).toHaveBeenCalledWith({ alarm_ids: ['one', 'two'] });
    vi.mocked(deleteAlarmSelection).mockRejectedValueOnce(new Error('Try again'));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete 2 anomalies' }));
    expect(await within(dialog).findByRole('alert')).toHaveProperty('textContent', 'Try again');
    vi.mocked(queryAlarms).mockResolvedValue(page([]));
    dialog = screen.getByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete 2 anomalies' }));
    await screen.findByText('No anomalies recorded.');
    expect(vi.mocked(deleteAlarmSelection).mock.calls).toEqual([['frozen'], ['frozen']]);
    expect(screen.queryByRole('region', { name: 'Selected anomalies' })).toBeNull();
  });

  it('deletes all matches using the active filter and clears selection when the filter changes', async () => {
    const router = mount('/anomalies?filterReading=temperature'); await loaded();
    fireEvent.click(rowCheckboxes()[0]!);
    fireEvent.change(screen.getByRole('combobox', { name: 'Reading' }), { target: { value: 'current' } });
    await waitFor(() => expect(router.state.location.search).toBe('?filterReading=current'));
    await loaded();
    expect(screen.queryByRole('region', { name: 'Selected anomalies' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Delete all matching' }));
    await screen.findByRole('dialog');
    expect(previewAlarmDeletion).toHaveBeenCalledWith({ query: { reading_id: 'current', limit: 500 } });
  });

  it('cancels a stale manual refresh when filters change', async () => {
    mount(); await loaded();
    let finish!: (value: AlarmPage) => void;
    vi.mocked(queryAlarms).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    const staleSignal = vi.mocked(queryAlarms).mock.lastCall![1]!;
    vi.mocked(queryAlarms).mockResolvedValue(page([second]));
    fireEvent.change(screen.getByRole('combobox', { name: 'Reading' }), { target: { value: 'current' } });
    await screen.findByRole('link', { name: 'Adaptive threshold exceeded' });
    await act(async () => finish(page([first])));
    expect(staleSignal.aborted).toBe(true);
    expect(screen.queryByRole('link', { name: 'Evidence threshold crossed' })).toBeNull();
  });
});

describe('anomaly investigation', () => {
  it('takes charger and sensor links to the event and focuses the selected signal', async () => {
    const router = mount(); await loaded();
    const row = screen.getByRole('link', { name: 'Evidence threshold crossed' }).closest('tr')!;
    expect(within(row).getByRole('link', { name: 'Charger 1' }).getAttribute('href')).toBe('/details/charger?event=one');
    fireEvent.click(within(row).getByRole('link', { name: 'Current' }));
    await screen.findByRole('region', { name: 'Chart current' });
    expect(router.state.location.pathname + router.state.location.search).toBe('/details/charger?event=one&signal=current');
    expect(screen.queryByRole('region', { name: 'Chart temperature' })).toBeNull();
    expect(getTelemetryRange).toHaveBeenCalledWith('current', {
      startMs: Date.parse('2026-10-10T12:24:58.000Z'), endMs: Date.parse('2026-10-10T12:35:00.000Z'), buckets: 600,
    }, expect.any(AbortSignal));
  });

  it('opens a historical event directly, links charts and keeps IDs in technical details', async () => {
    mount('/anomalies/one');
    const temperature = await screen.findByRole('region', { name: 'Chart temperature' });
    const current = screen.getByRole('region', { name: 'Chart current' });
    expect(queryAlarms).not.toHaveBeenCalled();
    expect(getAlarm).toHaveBeenCalledWith('one', expect.any(AbortSignal));
    expect(screen.getByText('3.20e-5')).toBeTruthy();
    expect(screen.getByText(/No per-sensor cause is established/)).toBeTruthy();
    const technical = screen.getByText('Technical details').closest('details')!;
    expect(technical.open).toBe(false);
    expect(within(technical).getByText('one')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Copy anomaly link' }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(`${window.location.origin}/anomalies/one`));
    fireEvent.click(within(temperature).getByRole('button', { name: 'Change time range' }));
    expect(within(current).getByRole('status').textContent).toBe(within(temperature).getByRole('status').textContent);
    await waitFor(() => expect(getTelemetryRange).toHaveBeenCalledWith('current', {
      startMs: Date.parse('2026-10-10T12:00:00Z'), endMs: Date.parse('2026-10-10T13:00:00Z'), buckets: 600,
    }, expect.any(AbortSignal)));
  });

  it('explains unavailable evidence and does not invent a sensor for unknown links', async () => {
    vi.mocked(getAlarm).mockResolvedValue({ alarm: first, evidence: null });
    mount('/anomalies/one?signal=unrelated');
    await screen.findByText(/Detailed detector evidence is unavailable/);
    expect(screen.getByText('This signal was not recorded as part of this anomaly.')).toBeTruthy();
    expect(getTelemetryRange).not.toHaveBeenCalled();
  });

  it('gives a deleted or expired event a recoverable error', async () => {
    vi.mocked(getAlarm).mockRejectedValue(new Error('This anomaly was deleted or is no longer retained'));
    mount('/anomalies/gone');
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('no longer retained'));
    expect(screen.getByRole('link', { name: 'Reporting' }).getAttribute('href')).toBe('/anomalies');
    expect(getTelemetryRange).not.toHaveBeenCalled();
  });

  it('uses detector decisions, exact trigger evidence and compact recency', () => {
    expect(anomalyDescription(first).title).toBe('Evidence threshold crossed');
    expect(anomalyDescription(second).title).toBe('Adaptive threshold exceeded');
    expect(anomalyTriggers(evidence)).toEqual([{ name: 'Restarted e-process · primary', value: '120', threshold: '100' }]);
    expect(compactRecency(at, Date.parse(at) + 27 * 60_000)).toBe('27m ago');
  });

  it('restores the actual scored reading when downsampling omitted it', async () => {
    const before = { timestamp: '2026-10-10T12:29:00Z', value: 20 };
    const after = { timestamp: '2026-10-10T12:31:00Z', value: 21 };
    const inputTime = '2026-10-10T12:30:00.123456Z';
    const time = epochMilliseconds(inputTime);
    const exact = { timestamp: inputTime, value: 35 };
    vi.mocked(getTelemetryRange).mockResolvedValueOnce([before, after]).mockResolvedValueOnce([exact]);
    const signal = new AbortController().signal;
    const range = { startMs: Date.parse(at) - 300_000, endMs: Date.parse(at) + 300_000 };
    expect(await getEventReadings('temperature', range, inputTime, signal)).toEqual([before, exact, after]);
    expect(getTelemetryRange).toHaveBeenLastCalledWith('temperature', {
      startMs: time, endMs: time + 0.001, buckets: 1,
    }, signal);
    const url = new URL(API_CONFIG.ENDPOINTS.READINGS.BUCKETS('temperature', { startMs: time, endMs: time + 0.001 }), window.location.origin);
    expect(url.searchParams.get('start')).toBe(inputTime);
    expect(url.searchParams.get('end')).toBe('2026-10-10T12:30:00.123457Z');
  });
});
