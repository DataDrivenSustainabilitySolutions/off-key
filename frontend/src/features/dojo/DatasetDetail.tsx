import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { InlineName } from "@/components/InlineName";
import { WorkspaceTabs } from "@/components/WorkspaceTabs";
import { useConfirm } from "@/hooks/use-confirm";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { usePollingLoop } from "@/hooks/use-polling";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetView, LabelView, RunSummary } from "@/types/dojo.generated";
import { dojoApi } from "./api";
import { ComparePanel } from "./ComparePanel";
import { LabelsPanel } from "./LabelsPanel";
import { RunsPanel } from "./RunsPanel";
import { DATASET_TABS as TABS, formatSpan, isActive, type DatasetTab } from "./model";

const RUN_POLL_MS = 3000;

export function DatasetDetail({ id, tab, listHref, focusTitle, onTab, onDeleted }: {
  id: string; tab: DatasetTab; listHref: string; focusTitle: boolean; onTab: (tab: DatasetTab) => void; onDeleted: () => void;
}) {
  const [dataset, setDataset] = useState<DatasetView | null>(null);
  const [labels, setLabels] = useState<LabelView[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [confirm, confirmation] = useConfirm();
  const title = useRef<HTMLHeadingElement>(null);
  const loadedId = dataset?.id;
  useEffect(() => {
    if (loadedId && focusTitle) title.current?.focus();
  }, [loadedId, focusTitle]);
  useDocumentTitle(dataset?.name, "Dojo");

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
    try {
      const page = await dojoApi.runs({ dataset_id: id, limit: 100 }, signal);
      if (!signal.aborted) setRuns(page.items);
    } catch (reason) {
      if (!signal.aborted) setError(getErrorMessage(reason));
    }
  }, [id]);
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
    <Link className="dj-back" to={listHref}><ArrowLeft size={14} />All datasets</Link>
    {error ? <p className="ex-banner ex-error" role="alert">{error}<button onClick={() => void datasetLoop.reload()}>Retry</button></p>
      : <p className="dj-loading" role="status">Loading dataset…</p>}
  </section>;
  return <section className="dj-page dj-detail" aria-label={`Dataset ${dataset.name}`}>
    <Link className="dj-back" to={listHref}><ArrowLeft size={14} />All datasets</Link>
    <div className="dj-detail-header">
      <div><h1 ref={title} tabIndex={-1} aria-label={dataset.name}><InlineName value={dataset.name} onSave={rename} ariaLabel="Rename dataset" /></h1>
        {dataset.description && <small>{dataset.description}</small>}</div>
      <div className="dj-detail-actions">
        <button type="button" className="dj-action" onClick={() => void remove()}><Trash2 size={15} />Delete</button>
      </div>
    </div>
    {deleteError && <p className="dj-error" role="alert">{deleteError}</p>}
    {error && <p className="ex-banner ex-error" role="alert">{error}</p>}
    <dl className="dj-summary">
      <div><dt>Values</dt><dd>{dataset.point_count.toLocaleString()}</dd></div>
      <div><dt>Series</dt><dd>{dataset.series.length}</dd></div>
      <div><dt>Labels</dt><dd>{labels.length}</dd></div>
      <div><dt>Runs</dt><dd>{runs.length}</dd></div>
      <div className="dj-summary-span"><dt>Time span</dt><dd>{formatSpan(dataset.start_at, dataset.end_at)}</dd></div>
    </dl>
    <WorkspaceTabs name="Dataset sections" idPrefix="dj" className="dj-tabs" tabs={TABS} selected={tab} onSelect={onTab} />
    <div id="dj-panel" role="tabpanel" aria-labelledby={`dj-tab-${tab}`} tabIndex={0}>
      {tab === "values" && <LabelsPanel dataset={dataset} labels={labels} onLabelsChange={reloadLabels} />}
      {tab === "runs" && <RunsPanel dataset={dataset} runs={runs} onRunsChange={runLoop.reload} />}
      {tab === "compare" && <ComparePanel dataset={dataset} runs={runs} labels={labels} />}
    </div>
    {confirmation}
  </section>;
}
