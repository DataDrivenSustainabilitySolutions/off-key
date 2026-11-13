import { Link, useLocation } from 'react-router-dom';
import { Activity, ArrowUpRight, Filter, Link2, Trash2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { ActionMenu } from '@/components/ActionMenu';
import { formatAnomalyValue, getAnomalyValueLabel, isProbabilityAnomalyValue } from '@/lib/anomaly-semantics';
import { formatExactDateTime, formatTimeOfDay } from '@/lib/format-time';
import { useCatalogue } from '@/features/workspace/catalogue-context';
import { alarmSource, sourceNode } from '@/features/workspace/reporting-scope';
import { selectedSourceHref } from '@/features/workspace/catalogue-navigation';
import { anomalyDescription, anomalyHref, anomalyReadingsHref, copyAnomalyLink } from './model';
import type { Alarm } from '@/types/charger';

export function AnomalyRow({ alarm, selected, canDelete, disabled, onSelect, onDelete, onNavigate }: {
  alarm: Alarm; selected: boolean; canDelete: boolean; disabled: boolean;
  onSelect: () => void; onDelete: () => void; onNavigate: (href: string) => void;
}) {
  const { system, index } = useCatalogue();
  const location = useLocation();
  const state = { reportingReturn: `${location.pathname}${location.search}` };
  const document = system.snapshot?.document;
  const source = alarmSource(alarm, document);
  const node = source && sourceNode(index, source);
  const description = anomalyDescription(alarm);
  const device = alarm.device_label ?? 'Removed source';
  return <tr className={`rp-row${selected ? ' rp-selected' : ''}`}>
    {canDelete && <td className="rp-select"><label className="rp-check"><input type="checkbox" aria-label={`Select ${device} at ${formatExactDateTime(alarm.timestamp)}`}
      checked={selected} disabled={disabled} onChange={onSelect} /></label></td>}
    <td className="rp-entity">
      {source ? <Link className="rp-source-link" state={state} to={anomalyReadingsHref(alarm, document)} title={`View ${device} at this event`}>
        {device}<ArrowUpRight size={12} aria-hidden="true" /></Link> : <span className="rp-source-name">{device}</span>}
      <div className="rp-time"><Link state={state} to={anomalyHref(alarm.alarm_id)} title={formatExactDateTime(alarm.timestamp)}>
        <time dateTime={alarm.timestamp}>{formatTimeOfDay(alarm.timestamp)}</time></Link></div>
    </td>
    <td className="rp-type"><Link state={state} to={anomalyHref(alarm.alarm_id)}>{description.title}</Link><small>{description.strategy}</small></td>
    <td className="rp-readings"><div>
      <div className="rp-reading-links">{alarm.reading_ids.map(id => <Link state={state} key={id} to={anomalyReadingsHref(alarm, document, id)}>
        {alarm.reading_labels[id] ?? id}</Link>)}</div>
      {alarm.multivariate && <span className="rp-context">{alarm.reading_ids.length || 'Multiple'} signals · joint result</span>}
      {!alarm.reading_ids.length && <span className="rp-context">{alarm.multivariate ? 'Involved signals unavailable' : 'Removed reading'}</span>}
    </div></td>
    <td className="rp-signal"><span className="rp-result" title={getAnomalyValueLabel(alarm.value_type)}>
      <span className="rp-result-label">{isProbabilityAnomalyValue(alarm.value_type) ? 'p' : 'Score'}</span>{' '}
      <span className="rp-result-value">{formatAnomalyValue(alarm.value, alarm.value_type)}</span></span></td>
    <td className="rp-actions"><ActionMenu label={`Actions for ${device} at ${formatExactDateTime(alarm.timestamp)}`} actions={[
      { label: 'Investigate anomaly', icon: Activity, onSelect: () => onNavigate(anomalyHref(alarm.alarm_id)) },
      { label: 'Copy anomaly link', icon: Link2, onSelect: () => void copyAnomalyLink(alarm.alarm_id)
        .then(() => toast.success('Anomaly link copied')).catch(() => toast.error('The link could not be copied.')) },
      ...(node ? [{ label: `Filter to ${device}`, icon: Filter, onSelect: () => onNavigate(selectedSourceHref('/anomalies', node)) }] : []),
      ...(canDelete && !disabled ? [{ label: 'Delete anomaly', icon: Trash2, destructive: true, separated: true, onSelect: onDelete }] : []),
    ]} /></td>
  </tr>;
}
