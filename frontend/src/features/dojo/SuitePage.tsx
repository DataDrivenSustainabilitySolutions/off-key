import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { ArrowLeft, BadgeCheck, Play, Square, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { useConfirm } from "@/hooks/use-confirm";
import { useDetailDocumentTitle } from "@/hooks/use-document-title";
import { usePollingLoop } from "@/hooks/use-polling";
import { getErrorMessage } from "@/lib/errors";
import type { StudyComparison, StudySummary, StudyView, SuiteView } from "@/types/dojo.generated";
import { dojoApi } from "./api";
import { formatInstant, formatPerDay, formatRate } from "./model";
import { ProtocolPanel } from "./ProtocolPanel";
import { StudyCreateDialog } from "./SuiteDialogs";
import { STUDY_METRICS, describePValue, formatScore, scoredOf, studyProgress, type StudyMetric } from "./suites";

const POLL_MS = 5000;
const ORIGIN = { csv: "CSV upload", history: "Recorded readings", benchmark: "Benchmark" } as const;

/** One suite: its datasets, its studies ranked, two studies compared, and one study dataset by dataset. */
export function SuitePage({ id, study, listHref, datasetHref, onStudy, onDeleted }: {
  id: string; study?: string; listHref: string; datasetHref: (id: string) => string;
  onStudy: (id: string | null) => void; onDeleted: () => void;
}) {
  const { can, isGuest } = useAuth();
  const editable = can("use_dojo");
  const [suite, setSuite] = useState<SuiteView | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [creating, setCreating] = useState(false);
  const [confirm, confirmation] = useConfirm();
  useDetailDocumentTitle(suite?.name ?? "Benchmark suite", "Dojo");
  const load = useCallback(async (signal: AbortSignal) => {
    try {
      const view = await dojoApi.suite(id, signal);
      if (!signal.aborted) { setSuite(view); setError(""); }
    } catch (reason) {
      if (!signal.aborted) setError(getErrorMessage(reason));
    }
  }, [id]);
  const waiting = !!suite?.unfinished.length;
  const { reload } = usePollingLoop(load, {
    startImmediately: true, intervalMs: waiting ? POLL_MS : undefined,
    schedule: "after-completion", pauseWhenHidden: true, resumeOnVisible: true,
  });
  const act = async (action: () => Promise<unknown>) => {
    setActionError("");
    try { await action(); await reload(); } catch (reason) { setActionError(getErrorMessage(reason)); }
  };
  const remove = async () => {
    if (!suite || !await confirm({ title: `Delete ${suite.name}?`,
      description: "Its studies and their runs go with it; its datasets stay. This cannot be undone.",
      confirmLabel: "Delete suite", destructive: true })) return;
    try { await dojoApi.deleteSuite(id); onDeleted(); }
    catch (reason) { setActionError(getErrorMessage(reason)); }
  };

  if (!suite) return <section className="dj-page">
    <Link className="dj-back" to={listHref}><ArrowLeft size={14} />All datasets and suites</Link>
    {error ? <p className="ex-banner ex-error" role="alert">{error}<button onClick={() => void reload()}>Retry</button></p>
      : <p className="dj-loading" role="status">Loading suite…</p>}
  </section>;
  const studies = [...suite.leaderboard, ...suite.unfinished];
  return <section className="dj-page dj-detail" aria-label={`Suite ${suite.name}`}>
    <Link className="dj-back" to={listHref}><ArrowLeft size={14} />All datasets and suites</Link>
    <div className="dj-detail-header">
      <div><h1>{suite.name}</h1>{suite.description && <small>{suite.description}</small>}</div>
      <div className="dj-detail-actions">
        {editable && <button type="button" className="dj-primary" onClick={() => setCreating(true)}><Play size={15} />New study</button>}
        {editable && !isGuest && !suite.reviewed && <button type="button" className="dj-action"
          onClick={() => void act(() => dojoApi.reviewSuite(id))}><BadgeCheck size={15} />Mark reviewed</button>}
        {editable && <button type="button" className="dj-action" onClick={() => void remove()}><Trash2 size={15} />Delete</button>}
      </div>
    </div>
    {actionError && <p className="dj-error" role="alert">{actionError}</p>}
    {error && <p className="ex-banner ex-error" role="alert">{error}</p>}
    <dl className="dj-summary">
      <div><dt>Datasets</dt><dd>{suite.items.length}</dd></div>
      <div><dt>Studies</dt><dd>{suite.studies}</dd></div>
      <div><dt>Made by</dt><dd>{suite.created_by_agent ? `Agent ${suite.created_by_agent}` : "A member"}</dd></div>
      <div><dt>Reviewed</dt><dd>{suite.reviewed ? "Yes" : "Not yet: an agent made it"}</dd></div>
      <div><dt>Created</dt><dd>{formatInstant(suite.created_at)}</dd></div>
    </dl>

    <h2 className="dj-section-head">Leaderboard</h2>
    <p className="dj-help">Only studies with every run finished and scored are ranked: by VUS-PR, then PR-AUC, then detection rate,
      each averaged over the datasets.</p>
    {suite.leaderboard.length === 0 ? <p className="dj-muted">No complete study yet.</p>
      : <StudyTable studies={suite.leaderboard} ranked current={study} onStudy={onStudy} />}
    {suite.unfinished.length > 0 && <>
      <h3 className="dj-section-head">Not yet ranked</h3>
      <StudyTable studies={suite.unfinished} current={study} onStudy={onStudy}
        onCancel={editable ? item => void act(() => dojoApi.cancelStudy(item.id)) : undefined}
        onDelete={editable ? item => void act(async () => {
          if (await confirm({ title: `Delete ${item.name || "this study"}?`, description: "Its runs and results go with it.",
            confirmLabel: "Delete study", destructive: true })) await dojoApi.deleteStudy(item.id);
        }) : undefined} />
    </>}

    {suite.leaderboard.length >= 2 && <StudyCompare suite={suite} />}
    {study && studies.some(item => item.id === study) && <StudyDetail key={study} id={study} datasetHref={datasetHref} />}

    <h2 className="dj-section-head">Datasets</h2>
    <div className="dj-table-scroll"><table className="dj-table" aria-label="Suite datasets">
      <thead><tr><th>Dataset</th><th>Origin</th><th>Series</th><th>Values</th><th>Labels</th></tr></thead>
      <tbody>{suite.items.map(item => <tr key={item.dataset_id}>
        <td><Link to={datasetHref(item.dataset_id)}>{item.name}</Link></td>
        <td>{ORIGIN[item.origin]}</td>
        <td>{item.series_names.join(", ")}</td>
        <td>{item.point_count.toLocaleString()}</td>
        <td>{item.labels}</td>
      </tr>)}</tbody>
    </table></div>
    <StudyCreateDialog open={creating} suite={suite} onOpenChange={setCreating}
      onCreated={created => { void reload(); onStudy(created.id); }} />
    {confirmation}
  </section>;
}

function StudyTable({ studies, ranked, current, onStudy, onCancel, onDelete }: {
  studies: StudySummary[]; ranked?: boolean; current?: string; onStudy: (id: string | null) => void;
  onCancel?: (study: StudySummary) => void; onDelete?: (study: StudySummary) => void;
}) {
  return <div className="dj-table-scroll"><table className="dj-table" aria-label={ranked ? "Ranked studies" : "Unfinished studies"}>
    <thead><tr>{ranked && <th>Rank</th>}<th>Study</th><th>VUS-PR</th><th>PR-AUC</th><th>AUROC</th><th>Detected</th>
      <th>False alarms per day</th><th>{ranked ? "Made" : "Progress"}</th>{(onCancel || onDelete) && <th />}</tr></thead>
    <tbody>{studies.map((item, index) => {
      const { totals } = item;
      const active = (item.runs.queued ?? 0) + (item.runs.running ?? 0) > 0;
      return <tr key={item.id} aria-current={item.id === current || undefined}>
        {ranked && <td>{index + 1}</td>}
        <td><button type="button" className="dj-link" onClick={() => onStudy(item.id === current ? null : item.id)}>
          {item.name || "Untitled study"}</button>
          {item.created_by_agent && <small>by agent {item.created_by_agent}</small>}</td>
        <td>{formatScore(totals.vus_pr)}<small>{scoredOf(totals, totals.vus_pr_runs)}</small></td>
        <td>{formatScore(totals.pr_auc)}<small>{scoredOf(totals, totals.pr_auc_runs)}</small></td>
        <td>{formatScore(totals.auroc)}<small>{scoredOf(totals, totals.auroc_runs)}</small></td>
        <td>{formatRate(totals.detection_rate)}<small>{totals.labels_detected} of {totals.labels_scored} labels</small></td>
        <td>{formatPerDay(totals.median_false_alarms_per_day)}<small>median</small></td>
        <td>{ranked ? formatInstant(item.created_at) : studyProgress(item)}</td>
        {(onCancel || onDelete) && <td className="dj-row-actions">
          {onCancel && active && <button type="button" className="dj-link" onClick={() => onCancel(item)}>
            <Square size={13} />Cancel</button>}
          {onDelete && !active && <button type="button" className="dj-link" onClick={() => onDelete(item)}>
            <Trash2 size={13} />Delete</button>}
        </td>}
      </tr>;
    })}</tbody>
  </table></div>;
}

/** Two complete studies paired dataset by dataset, with a Wilcoxon signed-rank test over the differences. */
function StudyCompare({ suite }: { suite: SuiteView }) {
  const [baseline, setBaseline] = useState(suite.leaderboard[1]?.id ?? "");
  const [challenger, setChallenger] = useState(suite.leaderboard[0]?.id ?? "");
  const [metric, setMetric] = useState<StudyMetric>("vus_pr");
  // A read belongs to the choice it answered, so a changed choice never shows an older answer.
  const asked = `${baseline}|${challenger}|${metric}`;
  const [read, setRead] = useState<{ asked: string; result?: StudyComparison; error?: string }>();
  const settled = read?.asked === asked ? read : undefined;
  const result = settled?.result ?? null;
  const error = settled?.error ?? "";
  useEffect(() => {
    if (!baseline || !challenger || baseline === challenger) return;
    const controller = new AbortController();
    const key = `${baseline}|${challenger}|${metric}`;
    dojoApi.compareStudies(suite.id, { baseline, challenger, metric }, controller.signal)
      .then(next => { if (!controller.signal.aborted) setRead({ asked: key, result: next }); })
      .catch(reason => { if (!controller.signal.aborted) setRead({ asked: key, error: getErrorMessage(reason) }); });
    return () => controller.abort();
  }, [suite.id, baseline, challenger, metric]);
  const names = Object.fromEntries(suite.leaderboard.map(item => [item.id, item.name || "Untitled study"]));
  const picker = (label: string, value: string, set: (value: string) => void) =>
    <label className="dj-field">{label}<select value={value} onChange={event => set(event.target.value)}>
      {suite.leaderboard.map(item => <option key={item.id} value={item.id}>{names[item.id]}</option>)}
    </select></label>;
  const metricLabel = STUDY_METRICS.find(item => item.id === metric)!.label;
  return <section className="dj-section" aria-label="Compare two studies">
    <h2 className="dj-section-head">Compare two studies</h2>
    <div className="dj-field-row">
      {picker("Baseline", baseline, setBaseline)}
      {picker("Challenger", challenger, setChallenger)}
      <label className="dj-field">Metric<select value={metric} onChange={event => setMetric(event.target.value as StudyMetric)}>
        {STUDY_METRICS.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>
    </div>
    {baseline === challenger && <p className="dj-muted">Choose two different studies.</p>}
    {error && <p className="dj-error" role="alert">{error}</p>}
    {result && baseline !== challenger && <>
      <p className="dj-help" role="status">{names[challenger]} is better on {result.wins}, worse on {result.losses} and level
        on {result.ties} of {result.compared} datasets by {metricLabel}; mean difference {formatScore(result.mean_delta)}.
        {" "}{describePValue(result.p_value)} (Wilcoxon signed-rank).</p>
      <div className="dj-table-scroll"><table className="dj-table" aria-label="Paired results">
        <thead><tr><th>Dataset</th><th>{names[baseline]}</th><th>{names[challenger]}</th><th>Difference</th></tr></thead>
        <tbody>{result.datasets.map(item => <tr key={item.dataset_id}>
          <td>{item.dataset_name}</td><td>{formatScore(item.baseline)}</td><td>{formatScore(item.challenger)}</td>
          <td>{item.delta == null ? "–" : `${item.delta > 0 ? "+" : ""}${item.delta.toFixed(3)}`}</td>
        </tr>)}</tbody>
      </table></div>
    </>}
  </section>;
}

/** One study's runs and metrics, dataset by dataset. Reading it calculates metrics still missing. */
function StudyDetail({ id, datasetHref }: { id: string; datasetHref: (id: string) => string }) {
  const [study, setStudy] = useState<StudyView | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async (signal: AbortSignal) => {
    try {
      const view = await dojoApi.study(id, signal);
      if (!signal.aborted) { setStudy(view); setError(""); }
    } catch (reason) {
      if (!signal.aborted) setError(getErrorMessage(reason));
    }
  }, [id]);
  const pending = !study || !study.complete;
  usePollingLoop(load, { startImmediately: true, intervalMs: pending ? POLL_MS : undefined,
    schedule: "after-completion", pauseWhenHidden: true, resumeOnVisible: true });
  if (!study) return error ? <p className="dj-error" role="alert">{error}</p> : <p className="dj-loading" role="status">Loading study…</p>;
  return <section className="dj-section" aria-label={`Study ${study.name}`}>
    <h2 className="dj-section-head">{study.name || "Untitled study"}</h2>
    <p className="dj-help">{studyProgress(study)}. Top-1 hits: {study.totals.top1_hits} of {study.totals.top1_runs} datasets
      with one label.</p>
    {error && <p className="dj-error" role="alert">{error}</p>}
    {study.protocol && <ProtocolPanel report={study.protocol} />}
    <div className="dj-table-scroll"><table className="dj-table" aria-label="Study runs">
      <thead><tr><th>Dataset</th><th>Run</th><th>VUS-PR</th><th>PR-AUC</th><th>AUROC</th><th>Detected</th><th>False alarms per day</th></tr></thead>
      <tbody>{study.items.map(item => {
        const metrics = item.metrics;
        return <tr key={item.run_id}>
          <td>{item.dataset_name}</td>
          <td><Link to={`${datasetHref(item.dataset_id)}&tab=runs&run=${encodeURIComponent(item.run_id)}`}>{item.status}</Link>
            {item.error && <small>{item.error}</small>}</td>
          <td>{formatScore(metrics?.scores?.vus_pr)}</td>
          <td>{formatScore(metrics?.scores?.pr_auc)}</td>
          <td>{formatScore(metrics?.scores?.auroc)}</td>
          <td>{metrics ? `${metrics.labels_detected} of ${metrics.labels_scored}` : "–"}</td>
          <td>{formatPerDay(metrics?.false_alarms_per_day)}</td>
        </tr>;
      })}</tbody>
    </table></div>
  </section>;
}
