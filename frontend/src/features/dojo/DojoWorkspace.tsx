import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetView } from "@/types/dojo.generated";
import { useCatalogue } from "../workspace/catalogue-context";
import { SelectedSourceBar } from "../workspace/SelectedSourceBar";
import { DatasetDetail } from "./DatasetDetail";
import { DatasetList } from "./DatasetList";
import { dojoApi } from "./api";
import { useDojoAccess } from "./access";
import { datasetTab, type DatasetTab } from "./model";
import "./dojo.css";

/** The Dojo: datasets, their labels, replayed runs and comparisons, apart from live monitoring. */
export function DojoWorkspace() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const allowed = useDojoAccess();
  const { selected, document } = useCatalogue();
  const datasetId = params.get("dataset");
  const runId = params.get("run");
  const [runError, setRunError] = useState<{ run: string; message: string }>();
  // A link to one run, such as a proposal's test, names only the run: its dataset is read first.
  useEffect(() => {
    if (!allowed || !runId || datasetId) return;
    const controller = new AbortController();
    void dojoApi.run(runId, controller.signal).then(
      (run) => { if (!controller.signal.aborted) setParams({ dataset: run.dataset_id, tab: "runs", run: run.id }, { replace: true }); },
      (reason) => { if (!controller.signal.aborted) setRunError({ run: runId, message: getErrorMessage(reason) }); },
    );
    return () => controller.abort();
  }, [allowed, runId, datasetId, setParams]);
  useDocumentTitle(!allowed ? "Access denied" : datasetId ? "Dataset" : "Datasets", "Dojo");
  const href = (next: Record<string, string | null>) => {
    const url = new URLSearchParams(params);
    for (const [key, value] of Object.entries(next)) {
      if (value === null) url.delete(key); else url.set(key, value);
    }
    const query = url.toString();
    return `/dojo${query ? `?${query}` : ""}`;
  };
  const readings = useMemo(() => {
    const ids = new Set(selected?.streamIds ?? []);
    return document.readings.filter(stream => ids.has(stream.id));
  }, [selected, document.readings]);
  // Choosing a source in the catalogue keeps the Dojo open: it picks what “Copy recorded
  // readings” starts from. Its readings page stays one link away.
  const scoped = selected && selected.kind !== "root" ? selected : undefined;
  const open = (dataset: DatasetView) => navigate(href({ dataset: dataset.id, tab: null, run: null }));

  return <main className="ex-main-content" aria-label="Dojo workspace">
    {!allowed ? <div className="dj-empty"><h2>The Dojo is not open to you</h2>
      <p>Ask a member who manages members for a role with the “Use the Dojo” permission.</p></div>
      : runId && !datasetId ? runError?.run === runId
        ? <div className="dj-empty"><h2>The run could not be opened</h2><p>{runError.message}</p></div>
        : <p className="dj-help" role="status">Opening the run…</p>
      : datasetId ? <DatasetDetail key={datasetId} id={datasetId} tab={datasetTab(params.get("tab"))} run={runId ?? undefined}
        listHref={href({ dataset: null, tab: null, run: null })}
        onTab={(tab: DatasetTab) => setParams(previous => { const next = new URLSearchParams(previous); next.set("tab", tab); return next; },
          { replace: true })}
        onDeleted={() => navigate(href({ dataset: null, tab: null, run: null }), { replace: true })} />
      : <DatasetList datasetHref={id => href({ dataset: id, tab: null, run: null })} onCreated={open}
        scope={scoped?.label} readings={readings} selection={<SelectedSourceBar />} />}
  </main>;
}
