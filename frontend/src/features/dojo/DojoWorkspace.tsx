import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetView } from "@/types/dojo.generated";
import { useCatalogue } from "../workspace/catalogue-context";
import { SelectedSourceBar } from "../workspace/SelectedSourceBar";
import { DatasetDetail } from "./DatasetDetail";
import { DatasetList, type DojoView } from "./DatasetList";
import { SuitePage } from "./SuitePage";
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
  const suiteId = params.get("suite");
  const view: DojoView = params.get("view") === "benchmarks" ? "benchmarks" : "datasets";
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
  useDocumentTitle(!allowed ? "Access denied" : datasetId ? "Dataset" : suiteId ? "Benchmark suite" : "Datasets", "Dojo");
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
  // A dataset opened from a suite leaves the suite: its link leads back to the list.
  const datasetHref = (id: string) => href({ dataset: id, suite: null, study: null, tab: null, run: null });
  const benchmarksHref = href({ view: "benchmarks", dataset: null, suite: null, study: null, tab: null, run: null });

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
      : suiteId ? <SuitePage key={suiteId} id={suiteId} study={params.get("study") ?? undefined} listHref={benchmarksHref}
        tab={params.get("tab") === "datasets" ? "datasets" : "studies"}
        onTab={tab => setParams(previous => { const next = new URLSearchParams(previous);
          if (tab === "datasets") next.set("tab", tab); else next.delete("tab"); return next; }, { replace: true })}
        datasetHref={datasetHref}
        onStudy={study => setParams(previous => { const next = new URLSearchParams(previous);
          if (study) next.set("study", study); else next.delete("study"); return next; })}
        onDeleted={() => navigate(benchmarksHref, { replace: true })} />
      : <DatasetList view={view} viewHref={next => href({ view: next === "datasets" ? null : next })} datasetHref={datasetHref} suiteHref={id => href({ suite: id, study: null })} onCreated={open}
        scope={scoped?.label} readings={readings} selection={<SelectedSourceBar />} />}
  </main>;
}
