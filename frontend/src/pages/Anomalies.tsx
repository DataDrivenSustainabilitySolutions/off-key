import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Activity, RefreshCw, Trash2, X } from 'lucide-react';
import { useAuth } from '@/auth/AuthContext';
import { PageShell } from '@/components/DashboardLayout';
import { HelpTooltip } from '@/components/HelpTooltip';
import { Button } from '@/components/ui/button';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useNow } from '@/hooks/use-now';
import { dayKey, formatDay, formatExactDateTime } from '@/lib/format-time';
import { useCatalogue } from '@/features/workspace/catalogue-context';
import { catalogueSelectionLabel, withCatalogueSource } from '@/features/workspace/catalogue-navigation';
import { detailsHref, selectedSource } from '@/features/workspace/reporting-scope';
import { AnomalyRow } from '@/features/reporting/AnomalyRow';
import { ReportingFilter } from '@/features/reporting/ReportingFilter';
import { useAlarmEvents } from '@/features/reporting/useAlarmEvents';
import { useAlarmDeletion } from '@/features/reporting/useAlarmDeletion';
import { compactRecency } from '@/features/reporting/model';
import type { Alarm, AlarmQuery } from '@/types/charger';
import '@/features/reporting/reporting.css';

const ranges = [{ id: 'any', label: 'Any time', ms: undefined }, { id: '24h', label: 'Last 24 hours', ms: 86_400_000 },
  { id: '7d', label: 'Last 7 days', ms: 7 * 86_400_000 }, { id: '30d', label: 'Last 30 days', ms: 30 * 86_400_000 }];
const probabilities = [{ id: 'any', label: 'All detector results' }, { id: '0.01', label: 'p ≤ 0.01' }, { id: '0.001', label: 'p ≤ 0.001' }];
const EMPTY_SELECTION = { key: '', all: false, ids: new Set<string>() };

export default function AnomalyTable() {
  const { can } = useAuth();
  const { streamIds, system, selected, selectionMissing, selectSource } = useCatalogue();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const reading = params.get('filterReading') ?? 'any';
  const range = ranges.find(item => item.id === params.get('range')) ?? ranges[0]!;
  const probability = probabilities.find(item => item.id === params.get('p')) ?? probabilities[0]!;
  const query = useMemo((): AlarmQuery => ({
    ...(streamIds !== undefined && { reading_ids: [...streamIds] }),
    ...(reading !== 'any' && { reading_id: reading }),
    ...(probability.id !== 'any' && { max_p_value: Number(probability.id) }), limit: 500,
  }), [streamIds, reading, probability.id]);
  const events = useAlarmEvents(query, range.ms);
  const { result, error, busy, loadingOlder } = events;
  const page = result?.page;
  const [selection, setSelection] = useState(EMPTY_SELECTION);
  const chosen = selection.key === events.key ? selection : EMPTY_SELECTION;
  const deletion = useAlarmDeletion(async () => { setSelection(EMPTY_SELECTION); await events.load(true); });
  const locked = deletion.busy || deletion.pending;
  const count = page?.summary.count ?? 0;
  const selectionCount = chosen.all ? Math.max(0, count - chosen.ids.size) : chosen.ids.size;
  const isSelected = (id: string) => chosen.all ? !chosen.ids.has(id) : chosen.ids.has(id);
  const items = useMemo(() => page?.items ?? [], [page]);
  const allVisible = items.length > 0 && items.every(alarm => isSelected(alarm.alarm_id));
  const someVisible = items.some(alarm => isSelected(alarm.alarm_id));
  const toggle = (ids: string[], select: boolean) => {
    const next = new Set(chosen.ids);
    for (const id of ids) { if (select !== chosen.all) next.add(id); else next.delete(id); }
    setSelection({ key: events.key, all: chosen.all, ids: next });
  };
  const now = useNow();
  const days = useMemo(() => {
    const groups: { key: string; label: string; rows: Alarm[] }[] = [];
    for (const alarm of items) {
      const key = dayKey(alarm.timestamp);
      if (groups[groups.length - 1]?.key !== key) groups.push({ key, label: formatDay(alarm.timestamp, now), rows: [] });
      groups[groups.length - 1]!.rows.push(alarm);
    }
    return groups;
  }, [items, now]);
  const document = system.snapshot?.document;
  const scopeLabel = (document && catalogueSelectionLabel(document, selected)) ?? (selectionMissing ? 'Unavailable selection' : 'All sources');
  const scopedSource = selectedSource(streamIds, document);
  const filtering = reading !== 'any' || range.id !== 'any' || probability.id !== 'any';
  const setFilter = (key: string, value: string) => setParams(previous => {
    const next = new URLSearchParams(previous);
    if (value === 'any') next.delete(key); else next.set(key, value);
    return next;
  });
  const clearFilters = () => setParams(previous => {
    const next = new URLSearchParams(previous);
    for (const key of ['filterReading', 'range', 'p']) next.delete(key);
    return next;
  });
  const readingOptions = useMemo(() => (page?.readings ?? []).map(item => ({ id: item.reading_id,
    label: `${item.label}${!scopedSource && item.device_label ? ` · ${item.device_label}` : ''}` }))
    .sort((a, b) => a.label.localeCompare(b.label)), [page, scopedSource]);
  const description = `${scopeLabel} · ${range.label}${reading !== 'any' ? ` · ${readingOptions.find(item => item.id === reading)?.label ?? reading}` : ''}${probability.id !== 'any' ? ` · ${probability.label}` : ''}.`;
  const canDelete = can('manage_alarms');
  const columns = canDelete ? 6 : 5;
  useDocumentTitle(scopeLabel === 'All sources' ? undefined : scopeLabel, 'Reporting');

  return <PageShell className="rp-page">
    <header className="rp-heading">
      <div className="rp-heading-main">
        <h1 className="app-page-title">Reporting</h1>
        {(selected || selectionMissing) && <div className="rp-source-scope" aria-label="Selected source">
          <span title={scopeLabel}>{scopeLabel}</span>
          <Button variant="ghost" size="icon" aria-label="Show all sources" title="Show all sources" disabled={locked} onClick={() => selectSource(null)}><X size={13} /></Button>
        </div>}
        <div className="rp-summary">
          <span>{page ? page.summary.devices : '—'} {page?.summary.devices === 1 ? 'device' : 'devices'}</span>
          <span>Latest · {page?.summary.latest ? <time dateTime={page.summary.latest} title={formatExactDateTime(page.summary.latest)}>
            {compactRecency(page.summary.latest, now)}</time> : page ? 'none' : '—'}</span>
        </div>
      </div>
      <div className="rp-heading-actions">
        {scopedSource && <Button variant="ghost" size="sm" asChild><Link to={withCatalogueSource(detailsHref(scopedSource), selected)}>
          <Activity size={14} />{scopedSource.kind === 'device' ? 'Device readings' : 'Broker readings'}</Link></Button>}
        <Button variant="ghost" size="icon" aria-label="Refresh" title={result ? `Refresh · Last updated ${formatExactDateTime(result.updatedAt)}` : 'Refresh'}
          onClick={() => void events.load()} disabled={busy || loadingOlder || locked}>
          <RefreshCw size={15} className={busy ? 'animate-spin' : ''} /></Button>
      </div>
    </header>
    {system.error && <p role="alert" className="rp-error">Catalogue status unavailable: {system.error}
      <Button variant="link" onClick={() => void system.refresh()}>Retry catalogue</Button></p>}
    {selectionMissing && <p role="alert" className="rp-error">This source is no longer available. Clear the signal scope to view other events.</p>}
    {error && <p role="alert" className="rp-error">Anomalies could not be updated: {error}. {page && 'Showing the last loaded results.'}
      <Button variant="outline" size="sm" disabled={busy || locked} onClick={() => void events.load()}>Retry</Button></p>}
    <section className="rp-events" aria-label="Anomaly events" aria-busy={busy}>
      <div className="rp-filters" role="group" aria-label="Filter events">
        <ReportingFilter label="Reading" value={reading} active={reading !== 'any'} disabled={locked} onChange={value => setFilter('filterReading', value)}
          options={[{ id: 'any', label: 'All readings' }, ...(reading !== 'any' && !readingOptions.some(item => item.id === reading)
            ? [{ id: reading, label: 'Selected reading (no results)' }] : []), ...readingOptions]} />
        <ReportingFilter label="Time range" value={range.id} options={ranges} active={range.id !== 'any'} disabled={locked} onChange={value => setFilter('range', value)} />
        <ReportingFilter label="p-value" value={probability.id} options={probabilities} active={probability.id !== 'any'} disabled={locked} onChange={value => setFilter('p', value)} />
        {filtering && <Button variant="ghost" size="sm" className="rp-clear-filters" disabled={locked} onClick={clearFilters}><X size={12} />Clear filters</Button>}
        <span className="rp-count" role="status">{page && `${count.toLocaleString()} ${count === 1 ? 'event' : 'events'}`}</span>
        {canDelete && count > 0 && selectionCount === 0 && <Button variant="ghost" size="sm" className="rp-delete-all" aria-label="Delete all matching" title="Delete all events matching this scope and these filters"
          disabled={busy || locked || !!error} onClick={() => result && void deletion.prepare({ query: result.query }, description)}><Trash2 size={13} />Delete all</Button>}
      </div>
      {probability.id !== 'any' && <p className="rp-note">This filter includes probability results only; adaptive scores are excluded.</p>}
      {selectionCount > 0 && <div className="rp-selection" role="region" aria-label="Selected anomalies">
        <strong>{selectionCount.toLocaleString()} selected{chosen.all ? ' across all pages' : ''}</strong>
        {!chosen.all && count > chosen.ids.size && <Button variant="link" size="sm" disabled={busy || locked}
          onClick={() => setSelection({ key: events.key, all: true, ids: new Set() })}>Select all {count.toLocaleString()} matching events</Button>}
        <Button variant="ghost" size="sm" className="rp-clear-selection" aria-label="Clear selection" title="Clear selection" disabled={locked} onClick={() => setSelection(EMPTY_SELECTION)}><X size={14} /></Button>
        <Button variant="default" size="sm" className="rp-delete-selected" disabled={busy || locked || !!error} onClick={() => result && void deletion.prepare(
          chosen.all ? { query: result.query, exclude_ids: [...chosen.ids] } : { alarm_ids: [...chosen.ids] }, description)}>
          <Trash2 size={14} />Delete selected</Button>
      </div>}
      {deletion.busy && !deletion.pending && <p role="status" className="rp-note">Preparing the exact selection…</p>}
      <table className={`rp-table${canDelete ? ' rp-selectable' : ''}`}>
        <thead><tr>
          {canDelete && <th scope="col" className="rp-select"><label className="rp-check"><input type="checkbox" aria-label="Select all loaded anomalies"
            ref={element => { if (element) element.indeterminate = someVisible && !allVisible; }}
            checked={allVisible} disabled={!items.length || busy || locked || !!error}
            onChange={event => toggle(items.map(alarm => alarm.alarm_id), event.target.checked)} /></label></th>}
          <th scope="col" className="rp-source-heading">Source</th><th scope="col" className="rp-detection-heading">Detection</th><th scope="col" className="rp-readings-heading">Involved signals</th>
          <th scope="col" className="rp-result-heading"><span className="rp-signal-heading">Result<HelpTooltip label="Detector result">
            A p-value describes how unusual an observation is. Scores depend on the detector. Investigate the event to see its alert threshold; these values do not measure operational severity.
          </HelpTooltip></span></th><th scope="col"><span className="sr-only">Actions</span></th>
        </tr></thead>
        {!page && busy ? <tbody><tr className="rp-message"><td colSpan={columns}>Loading anomalies…</td></tr></tbody>
          : !days.length ? <tbody><tr className="rp-message"><td colSpan={columns}>{error ? 'Events are unavailable.' : filtering || selected || selectionMissing
            ? 'No events match this scope and these filters.' : 'No anomalies recorded.'}</td></tr></tbody>
          : days.map(day => <tbody key={day.key}><tr className="rp-day"><th colSpan={columns} scope="rowgroup"><span>{day.label}</span></th></tr>
            {day.rows.map(alarm => <AnomalyRow key={alarm.alarm_id} alarm={alarm} selected={isSelected(alarm.alarm_id)} canDelete={canDelete}
              disabled={busy || locked || !!error} onSelect={() => toggle([alarm.alarm_id], !isSelected(alarm.alarm_id))}
              onNavigate={href => navigate(href, { state: { reportingReturn: `/anomalies${params.size ? `?${params}` : ''}` } })} onDelete={() => void deletion.prepare({ alarm_ids: [alarm.alarm_id] },
                `${alarm.device_label ?? 'Removed source'} at ${formatExactDateTime(alarm.timestamp)}.`)} />)}
          </tbody>)}
      </table>
      {page?.next && <div className="rp-more"><Button variant="outline" size="sm" disabled={busy || loadingOlder || locked}
        onClick={() => void events.loadOlder()}>{loadingOlder ? 'Loading older events…' : `Load older events (${Math.max(0, count - items.length).toLocaleString()} more)`}</Button></div>}
    </section>
    {deletion.confirmation}
  </PageShell>;
}
