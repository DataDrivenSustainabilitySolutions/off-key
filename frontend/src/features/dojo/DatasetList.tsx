import { useCallback, useState, type ReactNode } from "react";
import { useAuth } from "@/auth/AuthContext";
import { FileUp, FlaskConical, History } from "lucide-react";
import { Link } from "react-router-dom";
import { usePollingLoop } from "@/hooks/use-polling";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetSummary, DatasetView } from "@/types/dojo.generated";
import type { SystemStream } from "@/types/system";
import { dojoApi } from "./api";
import { BenchmarkImportDialog, CsvImportDialog, HistoryImportDialog } from "./DatasetImport";
import { formatInstant, formatSpan } from "./model";

const ORIGIN = { csv: "CSV upload", history: "Recorded readings", benchmark: "Benchmark" } as const;

export function DatasetList({ datasetHref, onCreated, scope, readings, selection }: {
  datasetHref: (id: string) => string;
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
  const [importing, setImporting] = useState<"csv" | "history" | "benchmark" | null>(null);
  const load = useCallback(async (signal: AbortSignal) => {
    try {
      const page = await dojoApi.datasets({ limit: 100 }, signal);
      if (!signal.aborted) { setDatasets(page.items); setError(""); }
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
      </div>}
    </header>
    {error && <p className="ex-banner ex-error" role="alert">{error}<button onClick={() => void reload()}>Retry</button></p>}
    {datasets === null && !error ? <p className="dj-loading" role="status">Loading datasets…</p>
      : datasets?.length === 0 ? <div className="dj-empty"><h2>No datasets yet</h2>
        <p>{editable ? "Upload a CSV file, add series of a public anomaly benchmark, or select a device or reading in the catalogue and copy its recorded readings for a time window." : "Datasets will appear here when the demo administrator adds them."}</p></div>
      : datasets && <div className="dj-table-scroll"><table className="dj-table" aria-label="Datasets">
        <thead><tr><th>Dataset</th><th>Origin</th><th>Values</th><th>Time span</th><th>Created</th></tr></thead>
        <tbody>{datasets.map(item => <tr key={item.id}>
          <td><Link to={datasetHref(item.id)}>{item.name}</Link>{item.description && <small>{item.description}</small>}</td>
          <td>{ORIGIN[item.origin]}</td>
          <td>{item.point_count.toLocaleString()}<small>{item.series_count} series</small></td>
          <td>{formatSpan(item.start_at, item.end_at)}</td>
          <td>{formatInstant(item.created_at)}</td>
        </tr>)}</tbody>
      </table></div>}
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
