import { useCallback, useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { FileUp, History } from "lucide-react";
import { Link } from "react-router-dom";
import { usePollingLoop } from "@/hooks/use-polling";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetSummary, DatasetView } from "@/types/dojo.generated";
import type { SystemStream } from "@/types/system";
import { dojoApi } from "./api";
import { CsvImportDialog, HistoryImportDialog } from "./DatasetImport";
import { formatInstant, formatSpan } from "./model";

const ORIGIN = { csv: "CSV upload", history: "Recorded readings" } as const;

export function DatasetList({ datasetHref, onCreated, scope, readings }: {
  datasetHref: (id: string) => string;
  onCreated: (dataset: DatasetView) => void;
  scope?: string;
  readings: SystemStream[];
}) {
  const { can } = useAuth();
  const editable = can("use_dojo");
  const [datasets, setDatasets] = useState<DatasetSummary[] | null>(null);
  const [error, setError] = useState("");
  const [importing, setImporting] = useState<"csv" | "history" | null>(null);
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
          which design finds them before you start monitoring.</p></div>
      {editable && <div className="dj-actions">
        <button type="button" className="dj-action" onClick={() => setImporting("csv")}><FileUp size={15} />Upload CSV</button>
        <button type="button" className="dj-action" onClick={() => setImporting("history")}><History size={15} />Copy recorded readings</button>
      </div>}
    </header>
    {error && <p className="ex-banner ex-error" role="alert">{error}<button onClick={() => void reload()}>Retry</button></p>}
    {datasets === null && !error ? <p className="dj-loading" role="status">Loading datasets…</p>
      : datasets?.length === 0 ? <div className="dj-empty"><h2>No datasets yet</h2>
        <p>{editable ? "Upload a CSV file, or select an entity in the catalogue and copy its recorded readings for a time window." : "Datasets will appear here when the demo administrator adds them."}</p></div>
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
    <HistoryImportDialog open={importing === "history"} onOpenChange={open => setImporting(open ? "history" : null)}
      onCreated={onCreated} scope={scope} readings={readings} />
  </section>;
}
