import { useCallback, useContext, useState } from "react";
import { FileUp, History } from "lucide-react";
import { Link } from "react-router-dom";
import { usePollingLoop } from "@/hooks/use-polling";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetSummary, DatasetView } from "@/types/dojo.generated";
import type { SystemStream } from "@/types/system";
import { CatalogueSearchContext } from "../workspace/catalogue-search";
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
  const [datasets, setDatasets] = useState<DatasetSummary[] | null>(null);
  const [error, setError] = useState("");
  const [importing, setImporting] = useState<"csv" | "history" | null>(null);
  const [choosingSource, setChoosingSource] = useState(false);
  const searchCatalogue = useContext(CatalogueSearchContext);
  const hasNumericReading = readings.some(reading => reading.value_type === "number");
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
        <p>Test detection designs on saved data before using them in live monitoring. Label known incidents and compare how each design responds.</p></div>
      <div className="dj-actions">
        <CsvImportDialog open={importing === "csv"} onOpenChange={open => setImporting(open ? "csv" : null)} onCreated={onCreated}
          trigger={<button type="button" className="dj-primary"><FileUp size={16} aria-hidden="true" />Upload CSV</button>} />
        <HistoryImportDialog open={importing === "history" || choosingSource && hasNumericReading} onOpenChange={open => {
          setChoosingSource(false);
          setImporting(open ? "history" : null);
        }} onChooseSource={searchCatalogue ? () => { setImporting(null); setChoosingSource(true); searchCatalogue(); } : undefined}
          onCreated={onCreated} scope={scope} readings={readings}
          trigger={<button type="button" className="dj-action"><History size={16} aria-hidden="true" />Copy recorded readings</button>} />
      </div>
    </header>
    {choosingSource && !hasNumericReading && <p className="ex-banner" role="status">
      Select a numeric reading in the catalogue to continue copying recorded data.{" "}
      <button type="button" onClick={() => setChoosingSource(false)}>Cancel selection</button>
    </p>}
    {error && <p className="ex-banner ex-error" role="alert">{error}<button onClick={() => void reload()}>Retry</button></p>}
    {datasets === null && !error ? <p className="dj-loading" role="status">Loading datasets…</p>
      : datasets?.length === 0 ? <div className="dj-empty"><h2>No datasets yet</h2>
        <p>Upload a CSV file, or select an entity in the catalogue and copy its recorded readings for a time window.</p></div>
      : datasets && <table className="dj-table dj-record-table" role="table" aria-label="Datasets">
        <thead role="rowgroup"><tr role="row">{["Dataset", "Origin", "Values", "Time span", "Created"].map(label =>
          <th key={label} scope="col" role="columnheader">{label}</th>)}</tr></thead>
        <tbody role="rowgroup">{datasets.map(item => <tr key={item.id} role="row">
          <th className="dj-record-name" scope="row" role="rowheader"><Link to={datasetHref(item.id)}>{item.name}</Link>
            {item.description && <small>{item.description}</small>}</th>
          <td role="cell"><span className="dj-cell-label" aria-hidden="true">Origin</span>{ORIGIN[item.origin]}</td>
          <td role="cell"><span className="dj-cell-label" aria-hidden="true">Values</span>
            {item.point_count.toLocaleString()}<small>{item.series_count} series</small></td>
          <td role="cell"><span className="dj-cell-label" aria-hidden="true">Time span</span>{formatSpan(item.start_at, item.end_at)}</td>
          <td role="cell"><span className="dj-cell-label" aria-hidden="true">Created</span>{formatInstant(item.created_at)}</td>
        </tr>)}</tbody>
      </table>}
  </section>;
}
