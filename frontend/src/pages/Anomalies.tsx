import { useAuth } from "@/auth/AuthContext";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Activity, Copy, Filter, RefreshCw, Trash2 } from "lucide-react";
import toast from "react-hot-toast";

import { ActionMenu } from "@/components/ActionMenu";
import { useConfirm } from "@/hooks/use-confirm";
import { MetricCard, PageHeader, PageShell } from "@/components/DashboardLayout";
import { RelativeTime } from "@/components/RelativeTime";
import { useNow } from "@/hooks/use-now";
import { Button } from "@/components/ui/button";
import { useDocumentTitle } from "@/hooks/use-document-title";
import {
  formatAnomalyValue,
  formatAnomalyEventType,
  getAnomalyValueClassName,
  getAnomalyValueLabel,
  isProbabilityAnomalyValue,
} from "@/lib/anomaly-semantics";
import { formatAnomalySensorSet, MULTIVARIATE_TELEMETRY_TYPE } from "@/lib/anomaly-utils";
import { deleteAnomaly, queryAnomalies } from "@/lib/charger-api";
import { getErrorMessage } from "@/lib/errors";
import { dayKey, formatDay, formatExactDateTime, formatTimeOfDay } from "@/lib/format-time";
import { useNavigationDraft } from "@/lib/navigation-draft";
import type { AnomalyPage, AnomalyQuery, ReportedAnomaly } from "@/types/charger";
import { useCatalogue } from "@/features/workspace/catalogue-context";
import { SourceScope } from "@/features/workspace/SourceScope";
import { entitySource, selectedEntity } from "@/features/workspace/reporting-scope";
import { selectedSourceHref, withCatalogueSource } from "@/features/workspace/catalogue-navigation";
import "./reporting.css";

const ranges = [{ id: "any", label: "Any time", ms: Infinity }, { id: "24h", label: "Last 24 hours", ms: 86_400_000 },
  { id: "7d", label: "Last 7 days", ms: 7 * 86_400_000 }, { id: "30d", label: "Last 30 days", ms: 30 * 86_400_000 }];
const signals = [{ id: "any", label: "All results", max: Infinity }, { id: "0.01", label: "p ≤ 0.01", max: 0.01 }, { id: "0.001", label: "p ≤ 0.001", max: 0.001 }];
const PAGE_SIZE = 500;
const readingId = (chargerId: string, key: string) => `${chargerId}\u0000${key}`;
/** The time window is relative to when the request is sent. */
const withSince = (query: AnomalyQuery, range: string): AnomalyQuery => {
  const window = ranges.find(item => item.id === range)?.ms ?? Infinity;
  return window === Infinity ? query : { ...query, since: new Date(Date.now() - window).toISOString() };
};

export default function AnomalyTable() {
  const { can, userId } = useAuth();
  const navigate = useNavigate();
  const { streamIds, system, selected, index } = useCatalogue();
  const [result, setResult] = useState<{ query: AnomalyQuery; page: AnomalyPage } | null>(null);
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
    const multipleEntities = new Set(readings.map(item => item.charger_id)).size > 1;
    return readings.map(item => [readingId(item.charger_id, item.telemetry_key),
      multipleEntities ? `${item.label} · ${item.entity_label}` : item.label] as const)
      .sort((left, right) => left[1].localeCompare(right[1]));
  }, [page]);
  // A remembered reading outside the current scope reads as "All readings".
  const activeReading = readingOptions.some(([id]) => id === reading) ? reading : "any";
  const query = useMemo((): AnomalyQuery => {
    const [chargerId, key] = activeReading.split("\u0000");
    const maximum = signals.find(item => item.id === signal)?.max ?? Infinity;
    return {
      ...(streamIds ? { stream_ids: [...streamIds] } : {}),
      ...(activeReading !== "any" ? { reading: { charger_id: chargerId!, telemetry_key: key! } } : {}),
      ...(maximum !== Infinity ? { max_p_value: maximum } : {}),
      limit: PAGE_SIZE,
    };
  }, [streamIds, activeReading, signal]);

  const load = useCallback(async (abort?: AbortSignal) => {
    const sent = withSince(query, range);
    try {
      setIsLoading(true);
      setError(null);
      const answer = await queryAnomalies(sent, abort);
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
      const older = await queryAnomalies({ ...result.query, before: result.page.next });
      setResult(current => current && current.query === result.query
        ? { query: current.query, page: { ...older, items: [...current.page.items, ...older.items] } }
        : current);
    } catch (err) {
      toast.error(`Older events could not be loaded: ${getErrorMessage(err)}`);
    } finally {
      setLoadingOlder(false);
    }
  };

  const runtime = system.snapshot?.runtime;
  const items = useMemo(() => page?.items ?? [], [page]);
  // One catalogue scan per entity, not one per table row and render.
  const sources = useMemo(() => new Map([...new Set(items.map(anomaly => anomaly.charger_id))]
    .map(id => [id, entitySource(index, system.snapshot?.document, runtime, id)] as const)),
  [items, index, system.snapshot?.document, runtime]);
  const days = useMemo(() => {
    const groups: Array<{ key: string; label: string; rows: ReportedAnomaly[] }> = [];
    for (const anomaly of items) {
      const key = dayKey(anomaly.timestamp);
      if (groups[groups.length - 1]?.key !== key) groups.push({ key, label: formatDay(anomaly.timestamp, now), rows: [] });
      groups[groups.length - 1]!.rows.push(anomaly);
    }
    return groups;
  }, [items, now]);
  const filtering = activeReading !== "any" || range !== "any" || signal !== "any";
  const clearFilters = () => { setReading("any"); setRange("any"); setSignal("any"); };
  const unknown = isLoading || (!!error && !page);
  const count = page?.summary.count ?? 0;
  const metric = (value: number) => unknown ? "—" : value;
  const scopedEntity = selectedEntity(streamIds, runtime);
  useDocumentTitle(selected?.label, "Reporting");

  const handleDelete = async (anomaly: ReportedAnomaly) => {
    if (!anomaly.anomaly_id) {
      toast.error("This anomaly has no ID and cannot be deleted.");
      return;
    }
    if (!await confirm({ title: "Delete this anomaly?", confirmLabel: "Delete anomaly", destructive: true,
      description: `${anomaly.entity_label} at ${formatExactDateTime(anomaly.timestamp)}. This cannot be undone.` })) return;
    try {
      await deleteAnomaly(anomaly.anomaly_id);

      toast.success("Anomaly deleted");
      await load();
    } catch (err) {
      toast.error(`The anomaly could not be deleted: ${getErrorMessage(err)}`);
    }
  };
  const copyEventDetail = async (value: string, label: string) => {
    try { await navigator.clipboard.writeText(value); toast.success(`${label} copied`); }
    catch { toast.error(`${label} could not be copied.`); }
  };

  return (
    <>
      <PageShell>
        <PageHeader
          title="Reporting"
          actions={<>
            {scopedEntity && <Button variant="ghost" asChild>
              <Link to={withCatalogueSource(`/details/${encodeURIComponent(scopedEntity)}`, selected)}><Activity className="h-4 w-4" />Entity readings</Link>
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
          {!scopedEntity && streamIds?.length !== 0 && <MetricCard
            label="Affected entities"
            value={metric(page?.summary.entities ?? 0)}
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
          <details className="rp-result-guide">
            <summary>How to read detector results</summary>
            <p>Event type describes the reported anomaly. Detector result identifies the statistic and its value.
              Lower p-values indicate more unusual readings. Red indicates p ≤ 0.001, orange p ≤ 0.005, and yellow a higher p-value.
              Other detector scores appear in grey.</p>
          </details>
          <table className="rp-table" role="table" aria-label="Reported anomaly events">
            <thead role="rowgroup">
              <tr role="row">
                <th scope="col" role="columnheader">Entity</th>
                <th scope="col" role="columnheader">Time</th>
                <th scope="col" role="columnheader">Readings</th>
                <th scope="col" role="columnheader">Event type</th>
                <th scope="col" role="columnheader">Detector result</th>
                <th scope="col" role="columnheader"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            {isLoading ? <tbody role="rowgroup"><tr role="row" className="rp-message"><td role="cell" colSpan={6}>Loading anomalies…</td></tr></tbody>
              : !days.length ? !error && <tbody role="rowgroup"><tr role="row" className="rp-message"><td role="cell" colSpan={6}>
                {filtering && readingOptions.length ? "No events match these filters." : "No anomalies recorded."}
              </td></tr></tbody>
              : days.map(day => <tbody key={day.key} role="rowgroup">
                <tr role="row" className="rp-day"><th role="rowheader" colSpan={6} scope="rowgroup">{day.label}</th></tr>
                {day.rows.map(anomaly => {
                  const entity = anomaly.entity_label;
                  const source = sources.get(anomaly.charger_id);
                  const scopedHere = !!source && source.key === selected?.key;
                  const sensors = formatAnomalySensorSet(anomaly.sensor_set?.length ? anomaly.readings.map(item => item.label) : anomaly.sensor_set);
                  return <tr key={anomaly.anomaly_id} role="row" className="rp-row">
                    <td role="cell" className="rp-entity">{source && !scopedHere
                      ? <Link to={selectedSourceHref("/anomalies", source)} title={`Show only ${entity}`}>{entity}</Link> : entity}
                      {anomaly.charger_id !== scopedEntity && <Link className="rp-entity-readings"
                        to={withCatalogueSource(`/details/${encodeURIComponent(anomaly.charger_id)}`, selected)}
                        aria-label={`View readings for ${entity}`}>View readings</Link>}
                    </td>
                    <td role="cell" className="rp-time"><time dateTime={anomaly.timestamp} title={formatExactDateTime(anomaly.timestamp)}>{formatTimeOfDay(anomaly.timestamp)}</time></td>
                    <td role="cell" className="rp-readings"><div>
                      <span className="rp-reading">{anomaly.telemetry_type === MULTIVARIATE_TELEMETRY_TYPE ? "multivariate" : anomaly.telemetry_label ?? anomaly.telemetry_type}</span>
                      {/* A single reading is already named by its badge. */}
                      {(anomaly.telemetry_type === MULTIVARIATE_TELEMETRY_TYPE || (anomaly.sensor_set?.length ?? 0) > 1) && <span className="rp-sensors" title={sensors}>{sensors}</span>}
                    </div></td>
                    <td role="cell" className="rp-type" title={anomaly.anomaly_type}>{formatAnomalyEventType(anomaly.anomaly_type)}</td>
                    <td role="cell" className="rp-signal"><span className={`rounded-full px-2.5 py-1 text-xs font-medium tabular-nums ${getAnomalyValueClassName(anomaly.anomaly_value, anomaly.value_type)}`}
                      title={getAnomalyValueLabel(anomaly.value_type)}>{isProbabilityAnomalyValue(anomaly.value_type) ? "p"
                        : getAnomalyValueLabel(anomaly.value_type)}{" "}{formatAnomalyValue(anomaly.anomaly_value, anomaly.value_type)}</span></td>
                    <td role="cell" className="rp-actions">
                      <ActionMenu label={`Actions for ${entity} at ${formatExactDateTime(anomaly.timestamp)}`} actions={[
                        ...(anomaly.charger_id !== scopedEntity ? [{ label: "Entity readings", icon: Activity, onSelect: () => navigate(withCatalogueSource(`/details/${encodeURIComponent(anomaly.charger_id)}`, selected)) }] : []),
                        ...(anomaly.anomaly_id ? [{ label: "Copy event ID", icon: Copy, onSelect: () => void copyEventDetail(anomaly.anomaly_id, "Event ID") }] : []),
                        { label: "Copy event type", icon: Copy, onSelect: () => void copyEventDetail(anomaly.anomaly_type, "Event type") },
                        ...(can("manage_alarms") ? [{ label: "Delete anomaly", icon: Trash2, destructive: true, separated: true, onSelect: () => void handleDelete(anomaly) }] : []),
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
