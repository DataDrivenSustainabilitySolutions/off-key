import { useCallback, useState, type ReactNode } from "react";
import { useAuth } from "@/auth/AuthContext";
import { FileUp, FlaskConical, History, ListChecks, Trash2, X } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/hooks/use-confirm";
import { usePollingLoop } from "@/hooks/use-polling";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetSummary, DatasetView, SuiteSummary } from "@/types/dojo.generated";
import type { SystemStream } from "@/types/system";
import { dojoApi } from "./api";
import { BenchmarkImportDialog, CsvImportDialog, HistoryImportDialog } from "./DatasetImport";
import { useSelection } from "./listing";
import { ListTable, type ListColumn } from "./ListTable";
import { formatInstant, formatShortDate, formatShortSpan, formatSpan } from "./model";
import { SuiteCreateDialog } from "./SuiteDialogs";

const ORIGIN = { csv: "CSV upload", history: "Recorded readings", benchmark: "Public benchmark" } as const;

/** The Dojo's front page shows either your own datasets or the benchmarks: suites and the public series they use. */
export type DojoView = "datasets" | "benchmarks";
const MODES: { id: DojoView; label: string }[] = [{ id: "datasets", label: "Datasets" }, { id: "benchmarks", label: "Benchmarks" }];

const plural = (count: number, one: string, many: string) => count === 1 ? one : many;
const created = <Row extends { created_at: string }>(): ListColumn<Row> => ({
  id: "created", label: "Created", wide: true, sort: row => row.created_at,
  cell: row => <time dateTime={row.created_at} title={formatInstant(row.created_at)}>{formatShortDate(row.created_at)}</time>,
});
const values: ListColumn<DatasetSummary> = { id: "values", label: "Values", numeric: true, sort: row => row.point_count,
  cell: row => row.point_count.toLocaleString(), unit: () => "values" };
const DATASET_COLUMNS: ListColumn<DatasetSummary>[] = [values,
  { id: "span", label: "Time span", sort: row => row.start_at ?? "",
    cell: row => <span title={formatSpan(row.start_at, row.end_at)}>{formatShortSpan(row.start_at, row.end_at)}</span> },
  created()];
// Public series run on made-up timestamps, so their span says nothing.
const SERIES_COLUMNS: ListColumn<DatasetSummary>[] = [values, created()];
const SUITE_COLUMNS: ListColumn<SuiteSummary>[] = [
  { id: "datasets", label: "Datasets", numeric: true, sort: row => row.datasets, cell: row => row.datasets,
    unit: row => plural(row.datasets, "dataset", "datasets") },
  { id: "studies", label: "Studies", numeric: true, sort: row => row.studies, cell: row => row.studies,
    unit: row => plural(row.studies, "study", "studies") },
  created()];
const NEWEST = { column: "created", descending: true };

export function DatasetList({ view, viewHref, datasetHref, suiteHref, onCreated, scope, readings, selection: catalogueSelection }: {
  view: DojoView;
  viewHref: (view: DojoView) => string;
  datasetHref: (id: string) => string;
  suiteHref: (id: string) => string;
  onCreated: (dataset: DatasetView) => void;
  scope?: string;
  readings: SystemStream[];
  /** The catalogue selection, with a link to its readings. */
  selection?: ReactNode;
}) {
  const { can } = useAuth();
  const editable = can("use_dojo");
  const [datasets, setDatasets] = useState<DatasetSummary[] | null>(null);
  const [error, setError] = useState("");
  const [suites, setSuites] = useState<SuiteSummary[]>([]);
  const [importing, setImporting] = useState<"csv" | "history" | "benchmark" | "suite" | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [confirm, confirmation] = useConfirm();
  const navigate = useNavigate();
  const load = useCallback(async (signal: AbortSignal) => {
    try {
      const [page, suitePage] = await Promise.all([dojoApi.datasets({ limit: 100 }, signal), dojoApi.suites({ limit: 100 }, signal)]);
      if (!signal.aborted) { setDatasets(page.items); setSuites(suitePage.items); setError(""); }
    } catch (reason) {
      if (!signal.aborted) setError(getErrorMessage(reason));
    }
  }, []);
  const { reload } = usePollingLoop(load, { startImmediately: true });
  const own = datasets?.filter(item => item.origin !== "benchmark") ?? null;
  const series = datasets?.filter(item => item.origin === "benchmark") ?? [];
  // One selection per view: suites and series share the benchmarks view's bar.
  const shown = view === "datasets" ? (own ?? []).map(item => item.id) : [...suites.map(item => item.id), ...series.map(item => item.id)];
  const selection = useSelection(shown);
  const pick = editable ? selection : undefined;
  const chosenSuites = suites.filter(item => selection.chosen.has(item.id));
  const chosenDatasets = (datasets ?? []).filter(item => selection.chosen.has(item.id) && shown.includes(item.id));

  const removeChosen = async () => {
    const parts = [chosenSuites.length && `${chosenSuites.length} ${plural(chosenSuites.length, "suite", "suites")}`,
      chosenDatasets.length && `${chosenDatasets.length} ${plural(chosenDatasets.length, "dataset", "datasets")}`].filter(Boolean);
    if (!await confirm({ title: `Delete ${parts.join(" and ")}?`,
      description: chosenDatasets.length
        ? "Datasets take their values, labels, runs and results with them; suites take their studies. This cannot be undone."
        : "Their studies and runs go with them; their datasets stay. This cannot be undone.",
      confirmLabel: "Delete", destructive: true })) return;
    setDeleting(true); setDeleteError("");
    try {
      const result = await dojoApi.deleteItems({ suite_ids: chosenSuites.map(item => item.id), dataset_ids: chosenDatasets.map(item => item.id) });
      const names = new Map([...chosenSuites, ...chosenDatasets].map(item => [item.id, item.name]));
      if (result.refused.length) setDeleteError(`${result.refused.length} could not be deleted. `
        + result.refused.map(item => `${names.get(item.id) ?? item.id}: ${item.reason}`).join(" "));
    } catch (reason) {
      setDeleteError(getErrorMessage(reason));
    } finally {
      setDeleting(false);
    }
    await reload();
  };

  const chosen = chosenSuites.length + chosenDatasets.length;
  return <section className="dj-page" aria-label="Dojo datasets">
    <header className="dj-header">
      <div><h1>Dojo</h1>
        <p>Try detection designs on data you already have, before they monitor anything.</p>
        {view === "datasets" && catalogueSelection}</div>
      {editable && (view === "datasets" ? <div className="dj-actions">
        <button type="button" className="dj-action" onClick={() => setImporting("csv")}><FileUp size={15} />Upload CSV</button>
        <button type="button" className="dj-action" onClick={() => setImporting("history")}><History size={15} />Copy recorded readings</button>
      </div> : <div className="dj-actions">
        <button type="button" className="dj-action" onClick={() => setImporting("benchmark")}><FlaskConical size={15} />Add public series</button>
        <button type="button" className="dj-primary" disabled={!datasets?.length} onClick={() => setImporting("suite")}><ListChecks size={15} />New suite</button>
      </div>)}
    </header>
    <nav className="dj-mode" aria-label="Dojo view">
      {MODES.map(item => <Link key={item.id} to={viewHref(item.id)} aria-current={view === item.id ? "page" : undefined}>
        {item.label}<span>{item.id === "datasets" ? own?.length ?? "" : suites.length}</span></Link>)}
    </nav>
    {error && <p className="ex-banner ex-error" role="alert">{error}<button onClick={() => void reload()}>Retry</button></p>}
    {deleteError && <p className="dj-error" role="alert">{deleteError}</p>}
    {chosen > 0 && <div className="dj-selection" role="region" aria-label="Selection">
      <strong>{chosen} selected</strong>
      <Button variant="ghost" size="sm" className="dj-clear-selection" aria-label="Clear selection" onClick={selection.clear}><X size={14} /></Button>
      <Button variant="default" size="sm" className="dj-delete-selected" disabled={deleting} onClick={() => void removeChosen()}>
        <Trash2 size={14} />{deleting ? "Deleting…" : "Delete selected"}</Button>
    </div>}
    {datasets === null && !error ? <p className="dj-loading" role="status">Loading…</p>
      : view === "datasets" ? own?.length === 0 ? <div className="dj-empty"><h2>No datasets yet</h2>
        <p>{editable ? "Upload a CSV file, or pick a device or reading in the catalogue and copy what it recorded." : "Datasets appear here when a member adds them."}</p></div>
        : own && <ListTable label="Datasets" rows={own} rowId={item => item.id} name={item => item.name} href={item => datasetHref(item.id)}
          note={item => <small>{ORIGIN[item.origin]}{item.series_count > 1 ? ` · ${item.series_count} series` : ""}</small>}
          columns={DATASET_COLUMNS} initial={NEWEST} selection={pick} />
      : <>
        {suites.length === 0 ? <div className="dj-empty"><h2>No benchmark suites yet</h2>
          <p>A suite is a fixed set of labelled datasets. Every design run over it is scored the same way, so designs can be ranked.</p></div>
          : <ListTable label="Benchmark suites" rows={suites} rowId={item => item.id} name={item => item.name} href={item => suiteHref(item.id)}
            note={item => item.created_by_agent && <small>By agent {item.created_by_agent}{item.reviewed ? "" : ", not yet reviewed"}</small>}
            columns={SUITE_COLUMNS} initial={NEWEST} selection={pick} />}
        {series.length > 0 && <>
          <h2 className="dj-section-title">Public series</h2>
          <ListTable label="Public series" rows={series} rowId={item => item.id} name={item => item.name} href={item => datasetHref(item.id)}
            columns={SERIES_COLUMNS} initial={{ column: "name", descending: false }} selection={pick} />
        </>}
      </>}
    <SuiteCreateDialog open={importing === "suite"} datasets={datasets ?? []} onOpenChange={open => setImporting(open ? "suite" : null)}
      onCreated={suite => navigate(suiteHref(suite.id))} />
    <CsvImportDialog open={importing === "csv"} onOpenChange={open => setImporting(open ? "csv" : null)} onCreated={onCreated} />
    <BenchmarkImportDialog open={importing === "benchmark"} onOpenChange={open => setImporting(open ? "benchmark" : null)}
      onImported={result => {
        // One series opens its dataset; several stay in the list.
        const [only] = result.items;
        if (result.items.length === 1 && only) void dojoApi.dataset(only.id).then(onCreated, () => void reload());
        else void reload();
      }} />
    <HistoryImportDialog open={importing === "history"} onOpenChange={open => setImporting(open ? "history" : null)}
      onCreated={onCreated} scope={scope} readings={readings} />
    {confirmation}
  </section>;
}
