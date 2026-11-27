import { useCallback, useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { ListChecks, Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Breadcrumb } from "@/components/Breadcrumb";
import { InlineName } from "@/components/InlineName";
import { useConfirm } from "@/hooks/use-confirm";
import { useDetailDocumentTitle } from "@/hooks/use-document-title";
import { usePollingLoop } from "@/hooks/use-polling";
import { getErrorMessage } from "@/lib/errors";
import { loadOffsetPages } from "@/lib/offset-pages";
import type { DatasetView, LabelView, RunSummary } from "@/types/dojo.generated";
import { dojoApi } from "./api";
import type { DojoView } from "./DatasetList";
import { LabelsPanel } from "./LabelsPanel";
import { RunsPanel } from "./RunsPanel";
import { FaultSuiteDialog } from "./SuiteDialogs";
import { DATASET_TABS as TABS, formatShortSpan, injectedFaults, isActive, type DatasetTab } from "./model";
import { LOCALE } from "@/lib/locale";

const RUN_POLL_MS = 3000;
const ORIGIN = { csv: "CSV upload", history: "Recorded readings", benchmark: "Public series" } as const;

export function DatasetDetail({ id, tab, run, listHref, onTab, onDeleted }: {
  id: string; tab: DatasetTab; onTab: (tab: DatasetTab) => void; onDeleted: () => void;
  /** The front page's view the dataset belongs to: public series sit under Benchmarks. */
  listHref: (view: DojoView) => string;
  /** A run to pick out among the runs, such as the test a proposal was handed in with. */
  run?: string;
}) {
  const { can } = useAuth();
  const editable = can("use_dojo");
  const [dataset, setDataset] = useState<DatasetView | null>(null);
  const [labels, setLabels] = useState<LabelView[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runPages, setRunPages] = useState(1);
  const [moreRuns, setMoreRuns] = useState(false);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [error, setError] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [confirm, confirmation] = useConfirm();
  const [faulting, setFaulting] = useState(false);
  const navigate = useNavigate();
  const name = dataset?.name ?? "Dataset";
  const tabLabel = TABS.find(item => item.id === tab)!.label;
  useDetailDocumentTitle(tab === "values" ? name : `${name} — ${tabLabel}`, "Dojo");

  const loadDataset = useCallback(async (signal: AbortSignal) => {
    try {
      const [view, labelList] = await Promise.all([dojoApi.dataset(id, signal), dojoApi.labels(id, signal)]);
      if (signal.aborted) return;
      setDataset(view); setLabels(labelList.items); setError("");
    } catch (reason) {
      if (!signal.aborted) setError(getErrorMessage(reason));
    }
  }, [id]);
  const datasetLoop = usePollingLoop(loadDataset, { startImmediately: true });
  const loadRuns = useCallback(async (signal: AbortSignal) => {
    setLoadingRuns(true);
    try {
      const page = await loadOffsetPages(offset => dojoApi.runs({ dataset_id: id, limit: 100, offset }, signal), runPages, signal);
      if (!signal.aborted) { setRuns(page.items); setMoreRuns(page.next_offset !== null); }
    } catch (reason) {
      if (!signal.aborted) setError(getErrorMessage(reason));
    } finally {
      if (!signal.aborted) setLoadingRuns(false);
    }
  }, [id, runPages]);
  const polling = runs.some(isActive);
  const runLoop = usePollingLoop(loadRuns, {
    startImmediately: true, intervalMs: polling ? RUN_POLL_MS : undefined,
    schedule: "after-completion", pauseWhenHidden: true, resumeOnVisible: true,
  });
  const reloadLabels = useCallback(async () => {
    setLabels((await dojoApi.labels(id)).items);
  }, [id]);

  const rename = async (name: string) => { setDataset(await dojoApi.changeDataset(id, { name })); };
  const remove = async () => {
    if (!dataset || !await confirm({ title: `Delete ${dataset.name}?`,
      description: "Its values, labels, runs and results go with it. This cannot be undone.",
      confirmLabel: "Delete dataset", destructive: true })) return;
    try { await dojoApi.deleteDataset(id); onDeleted(); }
    catch (reason) { setDeleteError(getErrorMessage(reason)); }
  };

  if (!dataset) return <section className="dj-page">
    <Breadcrumb steps={[{ label: "Dojo", onClick: () => navigate("/dojo") }]} current="Dataset" />
    {error ? <p className="ex-banner ex-error" role="alert">{error}<button onClick={() => void datasetLoop.reload()}>Retry</button></p>
      : <p className="dj-loading" role="status">Loading dataset…</p>}
  </section>;
  const faults = injectedFaults(dataset.source);
  const view: DojoView = dataset.origin === "benchmark" ? "benchmarks" : "datasets";
  const meta = [ORIGIN[dataset.origin], `${dataset.point_count.toLocaleString(LOCALE)} values`,
    ...(dataset.series.length > 1 ? [`${dataset.series.length} series`] : []),
    ...(dataset.origin === "benchmark" ? [] : [formatShortSpan(dataset.start_at, dataset.end_at)]),
    ...(faults ? [`injected faults ${faults}`] : [])];
  return <section className="dj-page dj-detail" aria-label={`Dataset ${dataset.name}`}>
    <Breadcrumb steps={[{ label: "Dojo", onClick: () => navigate("/dojo") },
      { label: view === "benchmarks" ? "Benchmarks" : "Datasets", onClick: () => navigate(listHref(view)) }]} current={dataset.name} />
    <div className="dj-detail-header">
      <div><h1><InlineName value={dataset.name} onSave={rename} editable={editable} ariaLabel="Rename dataset" /></h1>
        <p className="dj-meta">{dataset.description && <>{dataset.description}<br /></>}{meta.join(" · ")}</p></div>
      {editable && <div className="dj-detail-actions">
        <button type="button" className="dj-action" aria-label="Delete dataset" title="Delete dataset" onClick={() => void remove()}><Trash2 size={15} /></button>
        <button type="button" className="dj-action" onClick={() => setFaulting(true)}><ListChecks size={15} />Test with injected faults</button>
      </div>}
    </div>
    {deleteError && <p className="dj-error" role="alert">{deleteError}</p>}
    {error && <p className="ex-banner ex-error" role="alert">{error}</p>}
    <div className="dj-tabs" role="tablist" aria-label="Dataset sections">
      {TABS.map(item => <button key={item.id} type="button" role="tab" id={`dj-tab-${item.id}`} aria-selected={tab === item.id}
        aria-controls="dj-tab-panel" onClick={() => onTab(item.id)}>{item.label}
        <span className="dj-tab-count">{item.id === "values" ? labels.length : `${runs.length}${moreRuns ? "+" : ""}`}</span></button>)}
    </div>
    <div id="dj-tab-panel" role="tabpanel" aria-labelledby={`dj-tab-${tab}`}>
      {tab === "values" && <LabelsPanel dataset={dataset} labels={labels} onLabelsChange={reloadLabels} />}
      {tab === "runs" && <RunsPanel dataset={dataset} runs={runs} labels={labels} current={run} onRunsChange={runLoop.reload}
        more={moreRuns && <button type="button" className="dj-action" disabled={loadingRuns}
          onClick={() => setRunPages(count => count + 1)}>{loadingRuns ? "Loading runs…" : "Load more runs"}</button>} />}
    </div>
    {editable && <FaultSuiteDialog open={faulting} dataset={dataset} onOpenChange={setFaulting}
      onCreated={suite => navigate(`/dojo?suite=${encodeURIComponent(suite.id)}`)} />}
    {confirmation}
  </section>;
}
