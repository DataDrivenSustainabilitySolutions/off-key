import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Copy, Link2, Trash2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { useAuth } from '@/auth/AuthContext';
import { PageHeader, PageShell } from '@/components/DashboardLayout';
import { Button } from '@/components/ui/button';
import { useCatalogue } from '@/features/workspace/catalogue-context';
import { modelName } from '@/domain/monitoring/serviceModel';
import { alarmSource, detailsHref } from '@/features/workspace/reporting-scope';
import DynamicTelemetryChart from '@/features/charts/DynamicTelemetryChart';
import type { ChartNavigationState } from '@/features/charts/telemetry-chart';
import { getAlarm } from '@/lib/charger-api';
import { getErrorMessage } from '@/lib/errors';
import { formatExactDateTime } from '@/lib/format-time';
import { formatAnomalyValue, getAnomalyValueLabel } from '@/lib/anomaly-semantics';
import { useDocumentTitle } from '@/hooks/use-document-title';
import type { AlarmDetail, TelemetryTypeData } from '@/types/charger';
import { anomalyDescription, anomalyHref, anomalyTriggers, copyAnomalyLink, evidenceNumber } from './model';
import { useAlarmDeletion } from './useAlarmDeletion';
import { getEventReadings } from './readings';
import './reporting.css';

export default function AnomalyInvestigation({ eventId }: { eventId?: string }) {
  const { alarmId } = useParams();
  const id = eventId ?? alarmId ?? '';
  return <EventLoader key={id} id={id} />;
}

function EventLoader({ id }: { id: string }) {
  const [value, setValue] = useState<AlarmDetail>();
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getAlarm(id, controller.signal).then(result => { if (!controller.signal.aborted) { setValue(result); setError(''); } })
      .catch(error => { if (!controller.signal.aborted) setError(getErrorMessage(error)); });
    return () => controller.abort();
  }, [id, attempt]);
  if (value) return <EventView detail={value} />;
  return <PageShell className="rp-page"><Link to="/anomalies" className="rp-back"><ArrowLeft size={14} />Reporting</Link>
    <PageHeader title="Anomaly" />{error ? <div role="alert" className="rp-error">{error}
      <Button variant="outline" onClick={() => setAttempt(value => value + 1)}>Retry</Button></div>
      : <p role="status">Loading anomaly…</p>}</PageShell>;
}

function EventView({ detail }: { detail: AlarmDetail }) {
  const { alarm, evidence } = detail;
  const { can } = useAuth();
  const { system } = useCatalogue();
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const signal = params.get('signal');
  const description = anomalyDescription(alarm);
  const source = alarmSource(alarm, system.snapshot?.document);
  const triggers = anomalyTriggers(evidence);
  const returnPath = (location.state as { reportingReturn?: string } | null)?.reportingReturn;
  const back = returnPath === '/anomalies' || returnPath?.startsWith('/anomalies?') ? returnPath : '/anomalies';
  const deletion = useAlarmDeletion(async () => { navigate(back, { replace: true }); });
  const copyLink = () => void copyAnomalyLink(alarm.alarm_id).then(() => toast.success('Anomaly link copied'))
    .catch(() => toast.error('The anomaly link could not be copied.'));
  const copyId = () => void navigator.clipboard.writeText(alarm.alarm_id).then(() => toast.success('Event ID copied'))
    .catch(() => toast.error('The event ID could not be copied.'));
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const selectedIds = signal ? alarm.reading_ids.filter(id => id === signal) : alarm.reading_ids;
  const device = alarm.device_label ?? 'Removed source';
  useDocumentTitle(`${device} · ${description.title}`, 'Reporting');
  return <PageShell className="rp-page rp-investigation">
    <header className="rp-detail-heading">
      <Link to={back} className="rp-back" aria-label="Back to reporting"><ArrowLeft size={13} />Reporting</Link>
      <div className="rp-detail-title">
        <h1 className="app-page-title">{device}</h1>
        <p className="rp-event-time"><time dateTime={alarm.timestamp}>{formatExactDateTime(alarm.timestamp)}</time><span>{zone}</span></p>
      </div>
      <div className="rp-heading-actions">
        <Button variant="outline" size="sm" aria-label="Copy anomaly link" onClick={copyLink}><Link2 size={14} />Copy link</Button>
        {can('manage_alarms') && <Button variant="ghost" size="icon" aria-label="Delete anomaly" title="Delete anomaly" disabled={deletion.busy || deletion.pending}
          onClick={() => void deletion.prepare({ alarm_ids: [alarm.alarm_id] }, `${device} at ${formatExactDateTime(alarm.timestamp)}.`)}><Trash2 size={14} /></Button>}
      </div>
    </header>
    <section className="rp-event-summary" aria-label="Anomaly summary">
      <div className="rp-event-overview">
        <span className="rp-event-strategy">{description.strategy}</span>
        <h2>{description.title}</h2>
        <p className="rp-explanation">{description.explanation}</p>
        <div className="rp-reading-links rp-event-signals" aria-label="Involved signals">{alarm.reading_ids.map(id => <Link key={id}
          aria-current={signal === id ? 'page' : undefined} state={{ reportingReturn: back }} to={anomalyHref(alarm.alarm_id, id)}>{alarm.reading_labels[id] ?? id}</Link>)}</div>
        {alarm.multivariate && <p className="rp-note">Joint result across the involved signals. No per-sensor cause is established.</p>}
      </div>
      <dl className="rp-evidence-summary">{evidence?.strategy !== 'adaptive_stream' && <div><dt>{getAnomalyValueLabel(alarm.value_type)}</dt><dd>{formatAnomalyValue(alarm.value, alarm.value_type)}</dd></div>}
        {evidence?.model_type && <div><dt>Model</dt><dd>{modelName(evidence.model_type)}</dd></div>}
        {triggers.map(trigger => <div key={trigger.name} className="rp-trigger"><dt>{trigger.name}</dt><dd>{trigger.value} <span>threshold {trigger.threshold}</span></dd></div>)}
      </dl>
      <div className="rp-event-links">
        {signal && <Link to={anomalyHref(alarm.alarm_id)} state={{ reportingReturn: back }}>Show all involved signals</Link>}
        {source && <Link to={detailsHref(source)}>All {source.kind} readings</Link>}
        {alarm.monitor_id && <Link to={`/?${new URLSearchParams({ service: alarm.monitor_id, tab: 'evidence' })}`}>Originating monitor</Link>}
      </div>
      {!evidence && <p className="rp-note">Detailed detector evidence is unavailable for this event. It may have expired, or this event was recorded without it.</p>}
      {evidence && !triggers.length && <p className="rp-note">The exact triggering statistic was not recorded with this evidence.</p>}
      {!!evidence?.detector_results?.length && <details className="rp-technical"><summary>Detector contributions</summary>
        <p className="rp-note">Scores describe each detector's result, not individual sensor causation.</p>
        <dl>{evidence.detector_results.map(detector => <div key={detector.detector_id}><dt>{detector.detector_id}</dt>
          <dd>Score {evidenceNumber(detector.score)} · surprise {evidenceNumber(detector.surprise)}</dd></div>)}</dl>
      </details>}
    </section>
    {selectedIds.length ? <EventCharts key={`${alarm.alarm_id}:${signal ?? ''}`} detail={detail} ids={selectedIds} />
      : <p role="status" className="rp-note">{signal ? 'This signal was not recorded as part of this anomaly.' : 'The involved signals are no longer available in the catalogue.'}</p>}
    <details className="rp-technical"><summary>Technical details</summary>
      <p className="rp-note">The event ID identifies this stored anomaly in API requests and logs.</p>
      <dl><div><dt>Event ID</dt><dd><code>{alarm.alarm_id}</code><Button variant="ghost" size="sm" onClick={copyId}><Copy size={14} />Copy event ID</Button></dd></div>
        <div><dt>Recorded type</dt><dd><code>{alarm.alarm_type}</code></dd></div>
        <div><dt>Exact event time</dt><dd><code>{alarm.timestamp}</code></dd></div>
        <div><dt>Value type</dt><dd>{alarm.value_type ?? 'Not recorded'}</dd></div>
        {alarm.monitor_id && <div><dt>Monitor ID</dt><dd><code>{alarm.monitor_id}</code></dd></div>}
        {evidence && <div><dt>Evidence sequence</dt><dd>{evidence.sequence_number}</dd></div>}
        {Object.entries(evidence?.input_timestamps ?? {}).map(([id, timestamp]) => <div key={id}>
          <dt>{alarm.reading_labels[id] ?? id} · input time</dt><dd><code>{timestamp}</code></dd></div>)}
      </dl>
    </details>
    {deletion.confirmation}
  </PageShell>;
}

function EventCharts({ detail, ids }: { detail: AlarmDetail; ids: string[] }) {
  const { alarm, evidence } = detail;
  const { system } = useCatalogue();
  const initialNavigation = useMemo((): ChartNavigationState => {
    const times = [Date.parse(alarm.timestamp), ...ids.flatMap(id => evidence?.input_timestamps[id] ? [Date.parse(evidence.input_timestamps[id]!)] : [])].filter(Number.isFinite);
    const startMs = Math.min(...times) - 5 * 60_000, endMs = Math.max(...times) + 5 * 60_000;
    return { range: { fromMs: startMs, toMs: endMs }, viewport: { mode: 'absolute', startMs, endMs } };
  }, [alarm.timestamp, evidence, ids]);
  const [navigation, setNavigation] = useState(initialNavigation);
  const startMs = navigation.range.fromMs, endMs = navigation.range.toMs;
  const [attempt, setAttempt] = useState(0);
  const key = JSON.stringify([ids, startMs, endMs, attempt, evidence?.input_timestamps ?? {}]);
  const [loaded, setLoaded] = useState<{ key: string; series: TelemetryTypeData[]; failed: string[] }>();
  useEffect(() => {
    const controller = new AbortController();
    const [readings, start, end, , inputTimes] = JSON.parse(key) as [string[], number | null, number | null, number, Record<string, string | null>];
    const startMs = start ?? undefined, endMs = end ?? undefined;
    const timer = setTimeout(() => {
      void Promise.allSettled(readings.map(id => getEventReadings(id, { startMs, endMs }, inputTimes[id], controller.signal)))
        .then(results => {
          if (controller.signal.aborted) return;
          const failed: string[] = [];
          const series = results.flatMap((result, index) => {
            const id = readings[index]!;
            if (result.status === 'rejected') { failed.push(id); return []; }
            return [{ type: id, category: '', data: result.value }];
          });
          setLoaded({ key, series, failed });
        });
    }, 100);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [key]);
  const series = useMemo(() => (loaded?.series ?? []).map(series => ({ ...series,
    label: alarm.reading_labels[series.type] ?? series.type,
    unit: system.snapshot?.document.readings.find(reading => reading.id === series.type)?.unit,
  })), [loaded, alarm.reading_labels, system.snapshot]);
  const events = useMemo(() => [alarm], [alarm]);
  const observations = useMemo(() => evidence ? [evidence] : [], [evidence]);
  return <section className="rp-event-charts" aria-label="Anomaly readings" aria-busy={loaded?.key !== key}>
    <div className="rp-chart-heading"><div><h2>Recorded readings</h2>{ids.length > 1 && <span>Linked time ranges</span>}</div>
      <Button variant="ghost" size="sm" onClick={() => setNavigation(initialNavigation)}>Return to event</Button></div>
    {loaded?.key !== key && <p role="status">Loading recorded readings…</p>}
    {!!loaded?.failed.length && <p role="alert" className="rp-error">Some readings could not be loaded: {loaded.failed.map(id => alarm.reading_labels[id] ?? id).join(', ')}.
      <Button variant="outline" size="sm" onClick={() => setAttempt(value => value + 1)}>Retry readings</Button></p>}
    {series.map(series => <div key={series.type}>
      {!series.data.length && <p className="rp-note">No retained readings for {series.label} in this time window.</p>}
      <DynamicTelemetryChart historical telemetryData={series} anomalies={events} evidence={observations} navigationState={navigation}
        timelineExtent={startMs !== undefined && endMs !== undefined ? [startMs, endMs] : undefined}
        onNavigationStateChange={(_id, state) => setNavigation(state)} />
    </div>)}
  </section>;
}
