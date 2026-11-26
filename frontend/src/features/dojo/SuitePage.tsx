import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { BadgeCheck, GitCompareArrows, Play, Trash2, X } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/hooks/use-confirm";
import { useDetailDocumentTitle } from "@/hooks/use-document-title";
import { usePollingLoop } from "@/hooks/use-polling";
import { getErrorMessage } from "@/lib/errors";
import type { StudyComparison, StudySummary, StudyTotals, StudyView, SuiteView } from "@/types/dojo.generated";
import { dojoApi } from "./api";
import { useSelection } from "./listing";
import { formatPerDay, formatRate, formatShortDate } from "./model";
import { ProtocolPanel } from "./ProtocolPanel";
import { StudyCreateDialog } from "./SuiteDialogs";
import { STUDY_METRICS, describePValue, formatScore, studyProgress, type StudyMetric } from "./suites";

const POLL_MS = 5000;
const ORIGIN = { csv: "CSV upload", history: "Recorded readings", benchmark: "Public series" } as const;

export type SuiteTab = "studies" | "datasets";

/** One suite: its studies ranked in one list, two of them compared, and its datasets. A study opens as a page of its own. */
export function SuitePage({ id, study, tab, listHref, datasetHref, onStudy, onTab, onDeleted }: {
  id: string; study?: string; tab: SuiteTab; listHref: string; datasetHref: (id: string) => string;
  onStudy: (id: string | null) => void; onTab: (tab: SuiteTab) => void; onDeleted: () => void;
}) {
  const { can, isGuest } = useAuth();
  const editable = can("use_dojo");
  const navigate = useNavigate();
  const [suite, setSuite] = useState<SuiteView | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [creating, setCreating] = useState(false);
  const [comparing, setComparing] = useState<[string, string] | null>(null);
  const [confirm, confirmation] = useConfirm();
  const opened = study ? [...suite?.leaderboard ?? [], ...suite?.unfinished ?? []].find(item => item.id === study) : undefined;
  useDetailDocumentTitle(opened ? opened.name || "Untitled study" : suite?.name ?? "Benchmark suite", "Dojo");
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
  const studies = suite ? [...suite.leaderboard, ...suite.unfinished] : [];
  const selection = useSelection(studies.map(item => item.id));
  const act = async (action: () => Promise<unknown>) => {
    setActionError("");
    try { await action(); await reload(); } catch (reason) { setActionError(getErrorMessage(reason)); }
  };
  const remove = async () => {
    if (!suite || !await confirm({ title: `Delete ${suite.name}?`,
      description: "Its studies and their runs go with it; its datasets stay, and so does any run a proposal or monitor uses as its test. This cannot be undone.",
      confirmLabel: "Delete suite", destructive: true })) return;
    try { await dojoApi.deleteSuite(id); onDeleted(); }
    catch (reason) { setActionError(getErrorMessage(reason)); }
  };
  const back = [{ label: "Dojo", onClick: () => navigate("/dojo") }, { label: "Benchmarks", onClick: () => navigate(listHref) }];

  if (!suite) return <section className="dj-page">
    <Breadcrumb steps={back} current="Suite" />
    {error ? <p className="ex-banner ex-error" role="alert">{error}<button onClick={() => void reload()}>Retry</button></p>
      : <p className="dj-loading" role="status">Loading suite…</p>}
  </section>;
  if (study && opened) return <section className="dj-page dj-detail" aria-label={`Study ${opened.name}`}>
    <Breadcrumb steps={[...back, { label: suite.name, onClick: () => onStudy(null) }]} current={opened.name || "Untitled study"} />
    <StudyDetail key={study} id={study} datasetHref={datasetHref} />
  </section>;

  const chosen = studies.filter(item => selection.chosen.has(item.id));
  const ranked = new Set(suite.leaderboard.map(item => item.id));
  const pair = chosen.length === 2 && chosen.every(item => ranked.has(item.id)) ? chosen : null;
  const active = (item: StudySummary) => (item.runs.queued ?? 0) + (item.runs.running ?? 0) > 0;
  const removeChosen = async () => {
    if (!await confirm({ title: chosen.length === 1 ? `Delete ${chosen[0]!.name || "this study"}?` : `Delete ${chosen.length} studies?`,
      description: "Their runs and results go with them. This cannot be undone.", confirmLabel: "Delete", destructive: true })) return;
    let refused = "";
    await act(async () => {
      for (const item of chosen.filter(active)) await dojoApi.cancelStudy(item.id);
      const result = await dojoApi.deleteItems({ study_ids: chosen.map(item => item.id) });
      const names = new Map(chosen.map(item => [item.id, item.name || "Untitled study"]));
      refused = result.refused.map(item => `${names.get(item.id) ?? item.id}: ${item.reason}`).join(" ");
    });
    if (refused) setActionError(`Some studies could not be deleted. ${refused}`);
    selection.clear();
  };
  const meta = [`${suite.items.length} ${suite.items.length === 1 ? "dataset" : "datasets"}`,
    suite.created_by_agent ? `made by agent ${suite.created_by_agent}` : "made by a member",
    ...(suite.reviewed ? [] : ["not yet reviewed"]), `created ${formatShortDate(suite.created_at)}`];
  return <section className="dj-page dj-detail" aria-label={`Suite ${suite.name}`}>
    <Breadcrumb steps={back} current={suite.name} />
    <div className="dj-detail-header">
      <div><h1>{suite.name}</h1>
        <p className="dj-meta">{suite.description && <>{suite.description}<br /></>}{meta.join(" · ")}</p></div>
      <div className="dj-detail-actions">
        {editable && !isGuest && !suite.reviewed && <button type="button" className="dj-action"
          onClick={() => void act(() => dojoApi.reviewSuite(id))}><BadgeCheck size={15} />Mark reviewed</button>}
        {editable && <button type="button" className="dj-action" aria-label="Delete suite" title="Delete suite"
          onClick={() => void remove()}><Trash2 size={15} /></button>}
        {editable && <button type="button" className="dj-primary" onClick={() => setCreating(true)}><Play size={15} />New study</button>}
      </div>
    </div>
    {actionError && <p className="dj-error" role="alert">{actionError}</p>}
    {error && <p className="ex-banner ex-error" role="alert">{error}</p>}
    <div className="dj-tabs" role="tablist" aria-label="Suite sections">
      {(["studies", "datasets"] as const).map(item => <button key={item} type="button" role="tab" id={`dj-suite-tab-${item}`}
        aria-selected={tab === item} aria-controls="dj-suite-panel" onClick={() => onTab(item)}>
        {item === "studies" ? "Studies" : "Datasets"}<span className="dj-tab-count">{item === "studies" ? studies.length : suite.items.length}</span>
      </button>)}
    </div>
    <div id="dj-suite-panel" role="tabpanel" aria-labelledby={`dj-suite-tab-${tab}`} className="dj-tab-panel">
      {tab === "studies" ? <>
        {chosen.length > 0 && <div className="dj-selection" role="region" aria-label="Selection">
          <strong>{chosen.length} selected</strong>
          <Button variant="ghost" size="sm" className="dj-clear-selection" aria-label="Clear selection" onClick={selection.clear}><X size={14} /></Button>
          <span className="dj-selection-hint">{chosen.length === 1 ? "Choose one more ranked study to compare." : !pair ? "Only two ranked studies can be compared." : ""}</span>
          {editable && <Button variant="outline" size="sm" className="dj-delete-selected" onClick={() => void removeChosen()}><Trash2 size={14} />Delete</Button>}
          <Button variant="default" size="sm" disabled={!pair} onClick={() => pair && setComparing([pair[1]!.id, pair[0]!.id])}>
            <GitCompareArrows size={14} />Compare</Button>
        </div>}
        {studies.length === 0 ? <div className="dj-empty"><h2>No studies yet</h2>
          <p>A study runs one design over every dataset of this suite. Complete studies are ranked here.</p></div>
          : <StudyTable studies={studies} ranked={ranked} onStudy={onStudy} selection={editable || studies.length > 1 ? selection : undefined} />}
        {comparing && suite.leaderboard.length >= 2 && <StudyCompare key={comparing.join()} suite={suite} initial={comparing}
          onClose={() => setComparing(null)} />}
      </> : <div className="dj-table-scroll"><table className="dj-table dj-table--stack dj-list" aria-label="Suite datasets">
        <thead><tr><th>Dataset</th><th className="dj-fit dj-num">Values</th><th className="dj-fit dj-num">Labels</th></tr></thead>
        <tbody>{suite.items.map(item => <tr key={item.dataset_id}>
          <td className="dj-name"><Link to={datasetHref(item.dataset_id)}>{item.name}</Link>
            <small>{item.series_names.length > 1 ? `${item.series_names.length} series: ${item.series_names.join(", ")}` : ORIGIN[item.origin]}</small></td>
          <td className="dj-fit dj-num">{item.point_count.toLocaleString()}<span className="dj-narrow-unit"> values</span></td>
          <td className="dj-fit dj-num">{item.labels}<span className="dj-narrow-unit"> {item.labels === 1 ? "label" : "labels"}</span></td>
        </tr>)}</tbody>
      </table></div>}
    </div>
    <StudyCreateDialog open={creating} suite={suite} onOpenChange={setCreating}
      onCreated={created => { void reload(); onStudy(created.id); }} />
    {confirmation}
  </section>;
}

const RANK_HELP = "Only studies with every run finished and scored are ranked: by VUS-PR, then PR-AUC, then detection rate, each averaged over the datasets.";

/** Every study of a suite in one list: ranked ones first, then the ones still running, which show their progress instead of scores. */
function StudyTable({ studies, ranked, onStudy, selection }: {
  studies: StudySummary[]; ranked: ReadonlySet<string>; onStudy: (id: string | null) => void;
  selection?: { chosen: ReadonlySet<string>; toggle: (id: string, on: boolean) => void; setAll: (ids: string[], on: boolean) => void };
}) {
  const ids = studies.map(item => item.id);
  const count = ids.filter(id => selection?.chosen.has(id)).length;
  const score = (value: number | null | undefined, totals: StudyTotals, runs: number) =>
    <>{formatScore(value)}{runs < totals.runs_scored && <small>{runs} of {totals.runs_scored}</small>}</>;
  return <div className="dj-table-scroll"><table className={`dj-table dj-table--stack dj-list dj-studies${selection ? " dj-list--select" : ""}`} aria-label="Studies">
    <thead><tr>
      {selection && <th scope="col" className="dj-select"><label className="dj-check-box"><input type="checkbox" aria-label="Select all studies"
        checked={count > 0 && count === ids.length} ref={element => { if (element) element.indeterminate = count > 0 && count < ids.length; }}
        onChange={event => selection.setAll(ids, event.target.checked)} /><span className="dj-narrow-only">Select all</span></label></th>}
      <th scope="col" className="dj-fit dj-num dj-wide-only"><abbr title={RANK_HELP}>Rank</abbr></th>
      <th scope="col">Study</th>
      <th scope="col" className="dj-fit dj-num">VUS-PR</th>
      <th scope="col" className="dj-fit dj-num dj-wide-only">PR-AUC</th>
      <th scope="col" className="dj-fit dj-num dj-wide-only">AUROC</th>
      <th scope="col" className="dj-fit dj-num">Detected</th>
      <th scope="col" className="dj-fit dj-num"><abbr title="Median over the datasets">False alarms / day</abbr></th>
    </tr></thead>
    <tbody>{studies.map((item, index) => {
      const { totals } = item;
      const done = ranked.has(item.id);
      const on = !!selection?.chosen.has(item.id);
      return <tr key={item.id} className={[on && "dj-row-chosen", !done && "dj-row-pending"].filter(Boolean).join(" ") || undefined}>
        {selection && <td className="dj-select"><label className="dj-check-box"><input type="checkbox" checked={on}
          aria-label={`Select ${item.name || "Untitled study"}`} onChange={event => selection.toggle(item.id, event.target.checked)} /></label></td>}
        <td className="dj-fit dj-num dj-wide-only">{done ? index + 1 : ""}</td>
        <td className="dj-name"><button type="button" className="dj-row-link" onClick={() => onStudy(item.id)}>{item.name || "Untitled study"}</button>
          {(!done || item.created_by_agent) && <small>{[!done && studyProgress(item), item.created_by_agent && `by agent ${item.created_by_agent}`].filter(Boolean).join(" · ")}</small>}</td>
        {done ? <>
          <td className="dj-fit dj-num">{score(totals.vus_pr, totals, totals.vus_pr_runs)}<span className="dj-narrow-unit"> VUS-PR</span></td>
          <td className="dj-fit dj-num dj-wide-only">{score(totals.pr_auc, totals, totals.pr_auc_runs)}</td>
          <td className="dj-fit dj-num dj-wide-only">{score(totals.auroc, totals, totals.auroc_runs)}</td>
          <td className="dj-fit dj-num"><span title={`${totals.labels_detected} of ${totals.labels_scored} labels`}>{formatRate(totals.detection_rate)}</span>
            <span className="dj-narrow-unit"> detected</span></td>
          <td className="dj-fit dj-num">{formatPerDay(totals.median_false_alarms_per_day)}<span className="dj-narrow-unit"> false alarms a day</span></td>
        </> : <td className="dj-fit dj-wide-only" colSpan={5} />}
      </tr>;
    })}</tbody>
  </table></div>;
}

/** Two complete studies paired dataset by dataset, with a Wilcoxon signed-rank test over the differences. */
function StudyCompare({ suite, initial, onClose }: { suite: SuiteView; initial: [string, string]; onClose: () => void }) {
  const [baseline, setBaseline] = useState(initial[0]);
  const [challenger, setChallenger] = useState(initial[1]);
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
    <div className="dj-section-head"><h2>Compare two studies</h2>
      <button type="button" className="dj-link" onClick={onClose}>Close</button></div>
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
  return <section aria-label={`Study ${study.name}`}>
    <div className="dj-detail-header"><div><h1>{study.name || "Untitled study"}</h1>
      <p className="dj-meta">{studyProgress(study)} · top score at the label on {study.totals.top1_hits} of {study.totals.top1_runs} datasets with one label</p></div></div>
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
