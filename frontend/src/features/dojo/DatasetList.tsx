import { useCallback, useState, type ReactNode } from "react";
import { useAuth } from "@/auth/AuthContext";
import { FileUp, FlaskConical, History, ListChecks } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { usePollingLoop } from "@/hooks/use-polling";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetSummary, DatasetView, SuiteSummary } from "@/types/dojo.generated";
import type { SystemStream } from "@/types/system";
import { dojoApi } from "./api";
import { BenchmarkImportDialog, CsvImportDialog, HistoryImportDialog } from "./DatasetImport";
import { formatInstant, formatShortDate, formatShortSpan, formatSpan } from "./model";
import { SuiteCreateDialog } from "./SuiteDialogs";

const ORIGIN = { csv: "CSV upload", history: "Recorded readings", benchmark: "Benchmark" } as const;

export function DatasetList({ datasetHref, suiteHref, onCreated, scope, readings, selection }: {
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
  return <section className="dj-page" aria-label="Dojo datasets">
    <header className="dj-header">
      <div><h1>Dojo</h1>
        <p>Replay detection designs over recorded or uploaded data, mark the problems you already know about, and compare
          which design finds them before you start monitoring.</p>
        {selection}</div>
      {editable && <div className="dj-actions">
        <button type="button" className="dj-action" onClick={() => setImporting("csv")}><FileUp size={15} />Upload CSV</button>
        <button type="button" className="dj-action" onClick={() => setImporting("history")}><History size={15} />Copy recorded readings</button>
        <button type="button" className="dj-action" onClick={() => setImporting("benchmark")}><FlaskConical size={15} />Add benchmark</button>
        <button type="button" className="dj-action" disabled={!datasets?.length} onClick={() => setImporting("suite")}><ListChecks size={15} />New suite</button>
      </div>}
    </header>
    {error && <p className="ex-banner ex-error" role="alert">{error}<button onClick={() => void reload()}>Retry</button></p>}
    {datasets === null && !error ? <p className="dj-loading" role="status">Loading datasets…</p>
      : datasets?.length === 0 ? <div className="dj-empty"><h2>No datasets yet</h2>
        <p>{editable ? "Upload a CSV file, add series of a public anomaly benchmark, or select a device or reading in the catalogue and copy its recorded readings for a time window." : "Datasets will appear here when the demo administrator adds them."}</p></div>
      : datasets && <div className="dj-table-scroll"><table className="dj-table dj-table--stack" aria-label="Datasets">
        <thead><tr><th>Dataset</th><th className="dj-fit dj-wide-only">Origin</th><th className="dj-fit">Values</th>
          <th className="dj-fit">Time span</th><th className="dj-fit dj-wide-only">Created</th></tr></thead>
        <tbody>{datasets.map(item => <tr key={item.id}>
          <td><Link to={datasetHref(item.id)}>{item.name}</Link>{item.description && <small>{item.description}</small>}
            <small className="dj-narrow-only">{ORIGIN[item.origin]} · created {formatShortDate(item.created_at)}</small></td>
          <td className="dj-fit dj-wide-only">{ORIGIN[item.origin]}</td>
          <td className="dj-fit">{item.point_count.toLocaleString()}<span className="dj-narrow-unit"> values</span><small>{item.series_count} series</small></td>
          <td className="dj-fit"><span title={formatSpan(item.start_at, item.end_at)}>{formatShortSpan(item.start_at, item.end_at)}</span></td>
          <td className="dj-fit dj-wide-only"><time dateTime={item.created_at} title={formatInstant(item.created_at)}>{formatShortDate(item.created_at)}</time></td>
        </tr>)}</tbody>
      </table></div>}
    {suites.length > 0 && <>
      <h2 className="dj-section-head">Benchmark suites</h2>
      <p className="dj-help">Fixed sets of datasets. A study runs one design over all of them, and complete studies are ranked.</p>
      <div className="dj-table-scroll"><table className="dj-table" aria-label="Benchmark suites">
        <thead><tr><th>Suite</th><th>Datasets</th><th>Studies</th><th>Made by</th><th>Created</th></tr></thead>
        <tbody>{suites.map(item => <tr key={item.id}>
          <td><Link to={suiteHref(item.id)}>{item.name}</Link>{item.description && <small>{item.description}</small>}</td>
          <td>{item.datasets}</td>
          <td>{item.studies}</td>
          <td>{item.created_by_agent ? `Agent ${item.created_by_agent}` : "A member"}
            {!item.reviewed && <small>Not yet reviewed</small>}</td>
          <td>{formatInstant(item.created_at)}</td>
        </tr>)}</tbody>
      </table></div>
    </>}
    <SuiteCreateDialog open={importing === "suite"} datasets={datasets ?? []} onOpenChange={open => setImporting(open ? "suite" : null)}
      onCreated={suite => navigate(suiteHref(suite.id))} />
    <CsvImportDialog open={importing === "csv"} onOpenChange={open => setImporting(open ? "csv" : null)} onCreated={onCreated} />
    <BenchmarkImportDialog open={importing === "benchmark"} onOpenChange={open => setImporting(open ? "benchmark" : null)}
      onImported={result => {
        // One series opens its dataset; several stay in the list, newest first.
        const [only] = result.items;
        if (result.items.length === 1 && only) void dojoApi.dataset(only.id).then(onCreated, () => void reload());
        else void reload();
      }} />
    <HistoryImportDialog open={importing === "history"} onOpenChange={open => setImporting(open ? "history" : null)}
      onCreated={onCreated} scope={scope} readings={readings} />
  </section>;
}
