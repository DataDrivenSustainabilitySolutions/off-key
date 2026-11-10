import { useAuth } from "@/auth/AuthContext";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Activity, Copy, Filter, RefreshCw, Trash2 } from "lucide-react";
import toast from "react-hot-toast";

import { ActionMenu } from "@/components/ActionMenu";
import { useConfirm } from "@/hooks/use-confirm";
import { MetricCard, PageHeader, PageShell } from "@/components/DashboardLayout";
import { HelpTooltip } from "@/components/HelpTooltip";
import { RelativeTime } from "@/components/RelativeTime";
import { useNow } from "@/hooks/use-now";
import { Button } from "@/components/ui/button";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { catalogueSelectionLabel } from "@/features/workspace/catalogue-navigation";
import {
  formatAnomalyValue,
  getAnomalyValueClassName,
  getAnomalyValueLabel,
  isProbabilityAnomalyValue,
} from "@/lib/anomaly-semantics";
import { formatAlarmReadings, isAlarmContext } from "@/lib/anomaly-utils";
import { deleteAlarm, queryAlarms } from "@/lib/charger-api";
import { getErrorMessage } from "@/lib/errors";
import { dayKey, formatDay, formatExactDateTime, formatTimeOfDay } from "@/lib/format-time";
import { useNavigationDraft } from "@/lib/navigation-draft";
import type { Alarm, AlarmPage, AlarmQuery } from "@/types/charger";
import type { ExplorerNode } from "@/domain/system/navigationIndex";
import { useCatalogue } from "@/features/workspace/catalogue-context";
import { SourceScope } from "@/features/workspace/SourceScope";
import {
  alarmSource, detailsHref, selectedSource, sourceNode, type ReadingSource,
} from "@/features/workspace/reporting-scope";
import { selectedSourceHref, withCatalogueSource } from "@/features/workspace/catalogue-navigation";
import "./reporting.css";

const ranges = [{ id: "any", label: "Any time", ms: Infinity }, { id: "24h", label: "Last 24 hours", ms: 86_400_000 },
  { id: "7d", label: "Last 7 days", ms: 7 * 86_400_000 }, { id: "30d", label: "Last 30 days", ms: 30 * 86_400_000 }];
const signals = [{ id: "any", label: "All results", max: Infinity }, { id: "0.01", label: "p ≤ 0.01", max: 0.01 }, { id: "0.001", label: "p ≤ 0.001", max: 0.001 }];
const PAGE_SIZE = 500;
/** The device's name, or the broker's for readings without a device. */
const deviceName = (alarm: Alarm) => alarm.device_label ?? "Unknown device";
const sourceKey = (source: ReadingSource) => `${source.kind}:${source.id}`;
const readingsLabel = (source: ReadingSource) => source.kind === "device" ? "Device readings" : "Broker readings";
/** The time window is relative to when the request is sent. */
const withSince = (query: AlarmQuery, range: string): AlarmQuery => {
  const window = ranges.find(item => item.id === range)?.ms ?? Infinity;
  return window === Infinity ? query : { ...query, since: new Date(Date.now() - window).toISOString() };
};

export default function AnomalyTable() {
  const { can, userId } = useAuth();
  const navigate = useNavigate();
  const { streamIds, system, selected, index } = useCatalogue();
  const [result, setResult] = useState<{ query: AlarmQuery; page: AlarmPage } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [reading, setReading] = useNavigationDraft(`reporting:${userId}:reading`, "any");
  const [range, setRange] = useNavigationDraft(`reporting:${userId}:range`, "any");
  const [signal, setSignal] = useNavigationDraft(`reporting:${userId}:signal`, "any");
  const [confirm, confirmation] = useConfirm();
  const now = useNow();

  const page = result?.page;
  const readingOptions = useMemo(() => {
    const readings = page?.readings ?? [];
    const multipleDevices = new Set(readings.map(item => item.device_label)).size > 1;
    return readings.map(item => [item.reading_id,
      multipleDevices && item.device_label ? `${item.label} · ${item.device_label}` : item.label] as const)
      .sort((left, right) => left[1].localeCompare(right[1]));
  }, [page]);
  // A remembered reading outside the current scope reads as "All readings".
  const activeReading = readingOptions.some(([id]) => id === reading) ? reading : "any";
  const query = useMemo((): AlarmQuery => {
    const maximum = signals.find(item => item.id === signal)?.max ?? Infinity;
    return {
      ...(streamIds ? { reading_ids: [...streamIds] } : {}),
      ...(activeReading !== "any" ? { reading_id: activeReading } : {}),
      ...(maximum !== Infinity ? { max_p_value: maximum } : {}),
      limit: PAGE_SIZE,
    };
  }, [streamIds, activeReading, signal]);

  const load = useCallback(async (abort?: AbortSignal) => {
    const sent = withSince(query, range);
    try {
      setIsLoading(true);
      setError(null);
      const answer = await queryAlarms(sent, abort);
      if (!abort?.aborted) setResult({ query: sent, page: answer });
    } catch (err) {
      if (!abort?.aborted) setError(getErrorMessage(err));
    } finally {
      if (!abort?.aborted) setIsLoading(false);
    }
  }, [query, range]);

  useEffect(() => {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      void load(controller.signal);
    }, 0);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [load]);

  const loadOlder = async () => {
    if (!result?.page.next) return;
    setLoadingOlder(true);
    try {
      const older = await queryAlarms({ ...result.query, before: result.page.next });
      setResult(current => current && current.query === result.query
        ? { query: current.query, page: { ...older, items: [...current.page.items, ...older.items] } }
        : current);
    } catch (err) {
      toast.error(`Older events could not be loaded: ${getErrorMessage(err)}`);
    } finally {
      setLoadingOlder(false);
    }
  };

  const document = system.snapshot?.document;
  const items = useMemo(() => page?.items ?? [], [page]);
  // One catalogue node lookup per device or broker, not one per table row and render.
  const sources = useMemo(() => {
    const nodes = new Map<string, ExplorerNode | undefined>();
    return new Map(items.map(alarm => {
      const source = alarmSource(alarm, document);
      if (!source) return [alarm.alarm_id, undefined] as const;
      const key = sourceKey(source);
      if (!nodes.has(key)) nodes.set(key, sourceNode(index, source));
      return [alarm.alarm_id, { source, key, node: nodes.get(key) }] as const;
    }));
  }, [items, index, document]);
  const days = useMemo(() => {
    const groups: Array<{ key: string; label: string; rows: Alarm[] }> = [];
    for (const alarm of items) {
      const key = dayKey(alarm.timestamp);
      if (groups[groups.length - 1]?.key !== key) groups.push({ key, label: formatDay(alarm.timestamp, now), rows: [] });
      groups[groups.length - 1]!.rows.push(alarm);
    }
    return groups;
  }, [items, now]);
  const filtering = activeReading !== "any" || range !== "any" || signal !== "any";
  const clearFilters = () => { setReading("any"); setRange("any"); setSignal("any"); };
  const unknown = isLoading || (!!error && !page);
  const count = page?.summary.count ?? 0;
  const metric = (value: number) => unknown ? "—" : value;
  const scopedSource = selectedSource(streamIds, document);
  useDocumentTitle(document && catalogueSelectionLabel(document, selected), "Reporting");

  const handleDelete = async (alarm: Alarm) => {
    if (!await confirm({ title: "Delete this anomaly?", confirmLabel: "Delete anomaly", destructive: true,
      description: `${deviceName(alarm)} at ${formatExactDateTime(alarm.timestamp)}. This cannot be undone.` })) return;
    try {
      await deleteAlarm(alarm.alarm_id);

      toast.success("Anomaly deleted");
      await load();
    } catch (err) {
      toast.error(`The anomaly could not be deleted: ${getErrorMessage(err)}`);
    }
  };
  const copyId = async (id: string) => {
    try { await navigator.clipboard.writeText(id); toast.success("Event ID copied"); }
    catch { toast.error("The event ID could not be copied."); }
  };

  return (
    <>
      <PageShell>
        <PageHeader
          title="Reporting"
          actions={<>
            {scopedSource && <Button variant="ghost" asChild>
              <Link to={withCatalogueSource(detailsHref(scopedSource), selected)}><Activity className="h-4 w-4" />{readingsLabel(scopedSource)}</Link>
            </Button>}
            {!error && <Button
              variant="outline"
              onClick={() => void load()}
              disabled={isLoading}
            >
              <RefreshCw className={isLoading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
              Refresh
            </Button>}
          </>}
        />

        <SourceScope />
        {system.error && <p role="alert" className="flex flex-wrap items-center gap-x-3 text-sm text-destructive">Catalogue status unavailable: {system.error}
          <Button variant="link" className="h-auto px-0 sm:h-auto" onClick={() => void system.refresh()}>Retry catalogue</Button>
        </p>}
        <div className="rp-metrics">
          {!scopedSource && streamIds?.length !== 0 && <MetricCard
            label="Affected devices"
            value={metric(page?.summary.devices ?? 0)}
            tone="info"
          />}
          <MetricCard
            label="Last anomaly"
            value={unknown ? "—" : page?.summary.latest ? <RelativeTime value={page.summary.latest} /> : "None"}
          />
        </div>

        {error ? (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200">
            <span>Anomalies could not be loaded: {error}</span>
            <Button variant="outline" size="sm" onClick={() => void load()}>Retry</Button>
          </div>
        ) : null}

        <section className="rp-events" aria-label="Anomaly events">
          <div className="rp-filters" role="group" aria-label="Filter events">
            <Filter className="size-3.5 text-muted-foreground" aria-hidden="true" />
            <select aria-label="Reading" value={activeReading} onChange={event => setReading(event.target.value)} disabled={!readingOptions.length}>
              <option value="any">All readings</option>
              {readingOptions.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
            <select aria-label="Time range" value={range} onChange={event => setRange(event.target.value)}>
              {ranges.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
            <select aria-label="p-value" value={signal} onChange={event => setSignal(event.target.value)}>
              {signals.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
            {filtering && <Button variant="ghost" size="sm" onClick={clearFilters}>Clear filters</Button>}
            <span className="rp-count" role="status">{unknown ? "" : `${count.toLocaleString()} ${count === 1 ? "event" : "events"}`}</span>
          </div>
          <table className="rp-table">
            <thead>
              <tr>
                <th scope="col">Device</th>
                <th scope="col">Time</th>
                <th scope="col">Readings</th>
                <th scope="col">Type</th>
                <th scope="col"><span className="rp-signal-heading">Detector result<HelpTooltip label="Detector result">
                  Lower p-values indicate more unusual readings. Red means p ≤ 0.001, orange means p ≤ 0.005, and yellow means a higher p-value. Other detector scores are grey.
                </HelpTooltip></span></th>
                <th scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            {isLoading ? <tbody><tr className="rp-message"><td colSpan={6}>Loading anomalies…</td></tr></tbody>
              : !days.length ? !error && <tbody><tr className="rp-message"><td colSpan={6}>
                {filtering && readingOptions.length ? "No events match these filters." : "No anomalies recorded."}
              </td></tr></tbody>
              : days.map(day => <tbody key={day.key}>
                <tr className="rp-day"><th colSpan={6} scope="rowgroup">{day.label}</th></tr>
                {day.rows.map(alarm => {
                  const device = deviceName(alarm);
                  const found = sources.get(alarm.alarm_id);
                  const node = found?.node;
                  const scopedHere = !!node && node.key === selected?.key;
                  const readings = formatAlarmReadings(alarm);
                  return <tr key={alarm.alarm_id} className="rp-row">
                    <td className="rp-entity">{node && !scopedHere
                      ? <Link to={selectedSourceHref("/anomalies", node)} title={`Show only ${device}`}>{device}</Link> : device}</td>
                    <td className="rp-time"><time dateTime={alarm.timestamp} title={formatExactDateTime(alarm.timestamp)}>{formatTimeOfDay(alarm.timestamp)}</time></td>
                    <td className="rp-readings"><div>
                      <span className="rp-reading">{alarm.multivariate ? "multivariate" : alarm.reading_ids.length ? readings : "removed reading"}</span>
                      {/* A single reading is already named by its badge. */}
                      {isAlarmContext(alarm) && <span className="rp-sensors" title={readings}>{readings}</span>}
                    </div></td>
                    <td className="rp-type">{alarm.alarm_type}</td>
                    <td className="rp-signal"><span className={`rounded-full px-2.5 py-1 text-xs font-medium tabular-nums ${getAnomalyValueClassName(alarm.value, alarm.value_type)}`}
                      title={getAnomalyValueLabel(alarm.value_type)}>{isProbabilityAnomalyValue(alarm.value_type) ? "p" : "Score"}{" "}{formatAnomalyValue(alarm.value, alarm.value_type)}</span></td>
                    <td className="rp-actions">
                      <ActionMenu label={`Actions for ${device} at ${formatExactDateTime(alarm.timestamp)}`} actions={[
                        ...(found && found.key !== (scopedSource && sourceKey(scopedSource)) ? [{ label: readingsLabel(found.source), icon: Activity, onSelect: () => navigate(withCatalogueSource(detailsHref(found.source), selected)) }] : []),
                        { label: "Copy event ID", icon: Copy, onSelect: () => void copyId(alarm.alarm_id) },
                        ...(can("manage_alarms") ? [{ label: "Delete anomaly", icon: Trash2, destructive: true, separated: true, onSelect: () => void handleDelete(alarm) }] : []),
                      ]} />
                    </td>
                  </tr>;
                })}
              </tbody>)}
          </table>
          {page?.next && !isLoading && <div className="rp-more">
            <Button variant="outline" size="sm" onClick={() => void loadOlder()} disabled={loadingOlder}>
              {loadingOlder ? "Loading older events…" : `Load older events (${(count - items.length).toLocaleString()} more)`}
            </Button>
          </div>}
        </section>
      </PageShell>
      {confirmation}
    </>
  );
}
