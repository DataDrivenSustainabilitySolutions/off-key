import type { Alarm } from '@/types/charger';
import type { MonitoringChartEvidence } from '@/types/monitoring';
import type { SystemDocument } from '@/types/system';
import { alarmSource, detailsHref } from '@/features/workspace/reporting-scope';

const humanize = (value: string) => value.replace(/_/g, ' ').replace(/^./, first => first.toUpperCase());

/** Describe the detector's decision without inventing a physical cause. */
export function anomalyDescription(alarm: Alarm) {
  if (alarm.alarm_type.startsWith('ml_adaptive_stream_')) return {
    title: 'Adaptive threshold exceeded', strategy: 'Adaptive stream',
    explanation: 'The detector score exceeded its calibrated threshold.',
  };
  if (alarm.alarm_type.startsWith('ml_conformal_static_')) return {
    title: 'Evidence threshold crossed', strategy: 'Static baseline',
    explanation: 'Accumulated evidence crossed a configured alert threshold. The p-value describes this observation, not the full alert decision.',
  };
  if (alarm.alarm_type.startsWith('ml_tailprob_')) return {
    title: 'Unusual observation', strategy: 'Tail probability',
    explanation: 'A probability-based detector flagged this observation.',
  };
  return { title: humanize(alarm.alarm_type), strategy: alarm.monitor_id ? 'Detector event' : 'Recorded event',
    explanation: 'This event was recorded with the result shown below.' };
}

export const anomalyHref = (id: string, signal?: string) =>
  `/anomalies/${encodeURIComponent(id)}${signal ? `?signal=${encodeURIComponent(signal)}` : ''}`;

export function anomalyReadingsHref(alarm: Alarm, document?: SystemDocument, signal?: string) {
  const source = alarmSource(alarm, document);
  return source ? `${detailsHref(source)}?${new URLSearchParams({ event: alarm.alarm_id, ...(signal && { signal }) })}`
    : anomalyHref(alarm.alarm_id, signal);
}

export async function copyAnomalyLink(id: string) {
  await navigator.clipboard.writeText(new URL(anomalyHref(id), window.location.origin).href);
}

const statisticNames: Record<string, string> = {
  martingale: 'All-history martingale', restarted_martingale: 'Restarted e-process',
  cusum: 'CUSUM', shiryaev_roberts: 'Shiryaev–Roberts',
};
export const evidenceNumber = (value: number | null | undefined) => value == null ? 'Unavailable' : Number(value.toPrecision(5)).toString();

export function compactRecency(timestamp: string, now: number) {
  const minutes = Math.max(0, Math.floor((now - Date.parse(timestamp)) / 60_000));
  if (minutes === 0) return 'now';
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
  return `${Math.floor(minutes / 1440)}d ago`;
}
export function anomalyTriggers(evidence: MonitoringChartEvidence | null) {
  if (!evidence) return [];
  if (evidence.strategy === 'adaptive_stream') return [{ name: 'Detector score',
    value: evidenceNumber(evidence.anomaly_score), threshold: evidenceNumber(evidence.threshold) }];
  return (evidence.tracker_results ?? []).filter(tracker => tracker.alarm_fired).map(tracker => ({
    name: `${statisticNames[tracker.alarm_statistic] ?? humanize(tracker.alarm_statistic)} · ${tracker.tracker_id}`,
    value: tracker.statistic_is_infinite ? '∞' : evidenceNumber(tracker.statistic_value),
    threshold: evidenceNumber(tracker.threshold),
  }));
}
