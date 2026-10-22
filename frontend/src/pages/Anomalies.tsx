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
import {
  formatAnomalyValue,
  getAnomalyValueClassName,
  getAnomalyValueLabel,
  isProbabilityAnomalyValue,
} from "@/lib/anomaly-semantics";
import { formatAnomalySensorSet } from "@/lib/anomaly-utils";
import {
  deleteAnomaly,
  getAllChargers,
  getAnomalies,
} from "@/lib/charger-api";
import { getErrorMessage } from "@/lib/errors";
import { dayKey, formatDay, formatExactDateTime, formatTimeOfDay } from "@/lib/format-time";
import { useNavigationDraft } from "@/lib/navigation-draft";
import type { Anomaly } from "@/types/charger";
import { useCatalogue } from "@/features/workspace/catalogue-context";
import { SourceScope } from "@/features/workspace/SourceScope";
import { entitySource, filterSourceReports, reportLabels, selectedEntity } from "@/features/workspace/reporting-scope";
import { selectedSourceHref, withCatalogueSource } from "@/features/workspace/catalogue-navigation";
import "./reporting.css";

const MULTIVARIATE = "__multivariate__";
const ranges = [{ id: "any", label: "Any time", ms: Infinity }, { id: "24h", label: "Last 24 hours", ms: 86_400_000 },
  { id: "7d", label: "Last 7 days", ms: 7 * 86_400_000 }, { id: "30d", label: "Last 30 days", ms: 30 * 86_400_000 }];
const signals = [{ id: "any", label: "Any signal", max: Infinity }, { id: "0.01", label: "p ≤ 0.01", max: 0.01 }, { id: "0.001", label: "p ≤ 0.001", max: 0.001 }];
const readingKeys = (anomaly: Anomaly) => anomaly.sensor_set?.length ? anomaly.sensor_set
  : anomaly.telemetry_type === MULTIVARIATE ? [] : [anomaly.telemetry_type];
const anomalyKey = (anomaly: Anomaly) => anomaly.anomaly_id
  || `${anomaly.charger_id}-${anomaly.timestamp}-${anomaly.telemetry_type}-${anomaly.anomaly_type}`;

export default function AnomalyTable() {
  const { isAdmin, userId } = useAuth();
  const navigate = useNavigate();
  const { streamIds, system, selected, index } = useCatalogue();
  const [data, setData] = useState<Anomaly[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [reading, setReading] = useNavigationDraft(`reporting:${userId}:reading`, "any");
  const [range, setRange] = useNavigationDraft(`reporting:${userId}:range`, "any");
  const [signal, setSignal] = useNavigationDraft(`reporting:${userId}:signal`, "any");
  const [confirm, confirmation] = useConfirm();
  const now = useNow();

  const fetchAllAnomalies = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const chargers = await getAllChargers();
      const allAnomalies = await Promise.all(
        chargers.map((charger) => getAnomalies(charger.charger_id))
      );
      setData(allAnomalies.flat());
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    localStorage.setItem("off-key:last-seen-anomalies", new Date().toISOString());
    const timeoutId = window.setTimeout(() => {
      void fetchAllAnomalies();
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [fetchAllAnomalies]);

  const runtime = system.snapshot?.runtime;
  const labels = useMemo(() => reportLabels(system.snapshot?.document, runtime), [system.snapshot, runtime]);
  const scopedData = useMemo(() => filterSourceReports(data, streamIds, runtime), [data, streamIds, runtime]);
  const readingOptions = useMemo(() => {
    const options = new Map<string, string>();
    const multipleEntities = new Set(scopedData.map(anomaly => anomaly.charger_id)).size > 1;
    for (const anomaly of scopedData) for (const key of readingKeys(anomaly)) {
      const label = labels.reading(anomaly.charger_id, key);
      options.set(`${anomaly.charger_id}\u0000${key}`, multipleEntities ? `${label} · ${labels.entity(anomaly.charger_id)}` : label);
    }
    return [...options].sort((left, right) => left[1].localeCompare(right[1]));
  }, [scopedData, labels]);
  const activeReading = readingOptions.some(([id]) => id === reading) ? reading : "any";
  const filtered = useMemo(() => {
    const since = now - (ranges.find(item => item.id === range)?.ms ?? Infinity);
    const maximum = signals.find(item => item.id === signal)?.max ?? Infinity;
    const [entity, key] = activeReading.split("\u0000");
    return scopedData.filter(anomaly => (activeReading === "any" || anomaly.charger_id === entity && readingKeys(anomaly).includes(key!))
      && (range === "any" || Date.parse(anomaly.timestamp) >= since)
      && (maximum === Infinity || isProbabilityAnomalyValue(anomaly.value_type) && anomaly.anomaly_value <= maximum))
      .sort((left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp));
  }, [scopedData, activeReading, range, signal, now]);
  const days = useMemo(() => {
    const groups: Array<{ key: string; label: string; rows: Anomaly[] }> = [];
    for (const anomaly of filtered) {
      const key = dayKey(anomaly.timestamp);
      if (groups[groups.length - 1]?.key !== key) groups.push({ key, label: formatDay(anomaly.timestamp, now), rows: [] });
      groups[groups.length - 1]!.rows.push(anomaly);
    }
    return groups;
  }, [filtered, now]);
  const filtering = activeReading !== "any" || range !== "any" || signal !== "any";
  const clearFilters = () => { setReading("any"); setRange("any"); setSignal("any"); };
  const unknown = isLoading || (!!error && !data.length);
  const metric = (value: number) => unknown ? "—" : value;
  const scopedEntity = selectedEntity(streamIds, runtime);
  useDocumentTitle(selected?.label, "Reporting");

  const handleDelete = async (anomaly: Anomaly) => {
    if (!anomaly.anomaly_id) {
      toast.error("This anomaly has no ID and cannot be deleted.");
      return;
    }
    if (!await confirm({ title: "Delete this anomaly?", confirmLabel: "Delete anomaly", destructive: true,
      description: `${labels.entity(anomaly.charger_id)} at ${formatExactDateTime(anomaly.timestamp)}. This cannot be undone.` })) return;
    try {
      await deleteAnomaly(anomaly.anomaly_id);

      toast.success("Anomaly deleted");
      await fetchAllAnomalies();
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
            {scopedEntity && <Button variant="ghost" asChild>
              <Link to={withCatalogueSource(`/details/${encodeURIComponent(scopedEntity)}`, selected)}><Activity className="h-4 w-4" />Entity readings</Link>
            </Button>}
            <Button
              variant="outline"
              onClick={fetchAllAnomalies}
              disabled={isLoading}
            >
              <RefreshCw className={isLoading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
              Refresh
            </Button>
          </>}
        />

        <SourceScope />
        {system.error && <p role="alert" className="flex flex-wrap items-center gap-x-3 text-sm text-destructive">Catalogue status unavailable: {system.error}
          <Button variant="link" className="h-auto px-0 sm:h-auto" onClick={() => void system.refresh()}>Retry catalogue</Button>
        </p>}
        <div className="rp-metrics">
          <MetricCard
            label="Anomalies"
            value={metric(filtered.length)}
            tone={filtered.length > 0 ? "warning" : "default"}
          />
          <MetricCard
            label="Affected entities"
            value={metric(new Set(filtered.map(anomaly => anomaly.charger_id)).size)}
            tone="info"
          />
          <MetricCard
            label="Last anomaly"
            value={unknown ? "—" : filtered.length ? <RelativeTime value={filtered[0]!.timestamp} /> : "None"}
          />
        </div>

        {error ? (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200">
            <span>Anomalies could not be loaded: {error}</span>
            <Button variant="outline" size="sm" onClick={fetchAllAnomalies} disabled={isLoading}>Try again</Button>
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
            <select aria-label="Signal" value={signal} onChange={event => setSignal(event.target.value)}>
              {signals.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
            {filtering && <Button variant="ghost" size="sm" onClick={clearFilters}>Clear filters</Button>}
            <span className="rp-count" role="status">{isLoading ? "" : `${filtered.length.toLocaleString()} ${filtered.length === 1 ? "event" : "events"}`}</span>
          </div>
          <table className="rp-table">
            <thead>
              <tr>
                <th scope="col">Entity</th>
                <th scope="col">Time</th>
                <th scope="col">Readings</th>
                <th scope="col">Type</th>
                <th scope="col"><span className="rp-signal-heading">Signal<HelpTooltip label="Signal">
                  The detector's p-value: how likely a reading this extreme is under normal behaviour. Lower is more unusual.
                  Red is 0.001 or below, orange 0.005 or below, yellow above that. Scores without a p-value are grey.
                </HelpTooltip></span></th>
                <th scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            {isLoading ? <tbody><tr className="rp-message"><td colSpan={6}>Loading anomalies…</td></tr></tbody>
              : !days.length ? <tbody><tr className="rp-message"><td colSpan={6}>
                {error ? "Anomalies could not be loaded." : filtering && scopedData.length ? <>No events match these filters. <Button variant="link" className="h-auto px-0 sm:h-auto" onClick={clearFilters}>Clear filters</Button></>
                  : "No anomalies recorded."}
              </td></tr></tbody>
              : days.map(day => <tbody key={day.key}>
                <tr className="rp-day"><th colSpan={6} scope="rowgroup">{day.label}</th></tr>
                {day.rows.map(anomaly => {
                  const entity = labels.entity(anomaly.charger_id);
                  const source = entitySource(index, system.snapshot?.document, runtime, anomaly.charger_id);
                  const scopedHere = !!source && source.key === selected?.key;
                  const sensors = formatAnomalySensorSet(anomaly.sensor_set?.map(key => labels.reading(anomaly.charger_id, key)));
                  return <tr key={anomalyKey(anomaly)} className="rp-row">
                    <td className="rp-entity">{source && !scopedHere
                      ? <Link to={selectedSourceHref("/anomalies", source)} title={`Show only ${entity}`}>{entity}</Link> : entity}</td>
                    <td className="rp-time"><time dateTime={anomaly.timestamp} title={formatExactDateTime(anomaly.timestamp)}>{formatTimeOfDay(anomaly.timestamp)}</time></td>
                    <td className="rp-readings"><div>
                      <span className="rp-reading">{anomaly.telemetry_type === MULTIVARIATE ? "multivariate" : labels.reading(anomaly.charger_id, anomaly.telemetry_type)}</span>
                      {/* A single reading is already named by its badge. */}
                      {(anomaly.telemetry_type === MULTIVARIATE || (anomaly.sensor_set?.length ?? 0) > 1) && <span className="rp-sensors" title={sensors}>{sensors}</span>}
                    </div></td>
                    <td className="rp-type">{anomaly.anomaly_type}</td>
                    <td className="rp-signal"><span className={`rounded-full px-2.5 py-1 text-xs font-medium tabular-nums ${getAnomalyValueClassName(anomaly.anomaly_value, anomaly.value_type)}`}
                      title={getAnomalyValueLabel(anomaly.value_type)}>{formatAnomalyValue(anomaly.anomaly_value, anomaly.value_type)}</span></td>
                    <td className="rp-actions">
                      <ActionMenu label={`Actions for ${entity} at ${formatExactDateTime(anomaly.timestamp)}`} actions={[
                        ...(source && !scopedHere ? [{ label: `Show only ${entity}`, icon: Filter, onSelect: () => navigate(selectedSourceHref("/anomalies", source)) }] : []),
                        { label: "Entity readings", icon: Activity, onSelect: () => navigate(withCatalogueSource(`/details/${encodeURIComponent(anomaly.charger_id)}`, selected)) },
                        ...(anomaly.anomaly_id ? [{ label: "Copy event ID", icon: Copy, onSelect: () => void copyId(anomaly.anomaly_id) }] : []),
                        ...(isAdmin ? [{ label: "Delete anomaly", icon: Trash2, destructive: true, separated: true, onSelect: () => void handleDelete(anomaly) }] : []),
                      ]} />
                    </td>
                  </tr>;
                })}
              </tbody>)}
          </table>
        </section>
      </PageShell>
      {confirmation}
    </>
  );
}
