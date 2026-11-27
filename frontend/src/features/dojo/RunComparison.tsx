import { epochMilliseconds } from "@/lib/timestamps";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { getErrorMessage } from "@/lib/errors";
import type { Comparison, DatasetView, LabelView, RunMetrics, RunSummary } from "@/types/dojo.generated";
import { DOJO_LIMITS } from "@/types/dojo.generated";
import { ChartKey } from "../charts/ChartKey";
import { EChart } from "../charts/EChart";
import { useChartColors } from "../charts/use-chart-colors";
import { dojoApi } from "./api";
import { datasetChartOption } from "./dojo-chart";
import { useRunAlarms, useSeriesPoints } from "./hooks";
import { MethodsPanel } from "./MethodsPanel";
import { formatScore } from "./suites";
import { formatDuration, formatInstant, formatPerDay, formatRate, runName } from "./model";
import { LOCALE } from "@/lib/locale";

const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
const CHART_SERIES = 2;

type Row = {
  label: string;
  /** Shown before "All metrics" is opened. */
  key?: true;
  /** What the metric measures, on hover. */
  help?: string;
  value: (metrics: RunMetrics) => string;
  /** Lower or higher is better; the best run is shown in bold. */
  best?: { score: (metrics: RunMetrics) => number | null | undefined; prefer: "high" | "low" };
};

const ROWS: Row[] = [
  { label: "Labels detected", key: true, help: "Labels the run alarmed inside. Labels before the first score are not scored.",
    value: item => `${item.labels_detected} of ${item.labels_scored}`,
    best: { score: item => item.labels_detected, prefer: "high" } },
  { label: "Detection rate", value: item => formatRate(item.detection_rate),
    best: { score: item => item.detection_rate, prefer: "high" } },
  { label: "Median delay", key: true, help: "How long after a label began the run first alarmed, for the median label.", value: item => formatDuration(item.median_delay_seconds),
    best: { score: item => item.median_delay_seconds, prefer: "low" } },
  { label: "Longest delay", value: item => formatDuration(item.max_delay_seconds) },
  { label: "False alarms", value: item => item.false_alarms.toLocaleString(LOCALE),
    best: { score: item => item.false_alarms, prefer: "low" } },
  { label: "False alarms per day", key: true,
    help: "Alarms that begin outside every label, per day outside the labels. An alarm held for many values counts once.", value: item => formatPerDay(item.false_alarms_per_day),
    best: { score: item => item.false_alarms_per_day, prefer: "low" } },
  { label: "Time outside labels", value: item => formatDuration(item.evaluated_seconds) },
  // Threshold-free: how well the scores rank labelled results above the rest.
  { label: "PR-AUC", help: "How well the scores rank labelled values above the rest, before any threshold.", value: item => formatScore(item.scores?.pr_auc),
    best: { score: item => item.scores?.pr_auc, prefer: "high" } },
  { label: "VUS-PR", key: true,
    help: "Like PR-AUC, but also credits scores that peak just before or after a label.", value: item => formatScore(item.scores?.vus_pr),
    best: { score: item => item.scores?.vus_pr, prefer: "high" } },
  { label: "AUROC", help: "The chance that a labelled value scores above an ordinary one.", value: item => formatScore(item.scores?.auroc),
    best: { score: item => item.scores?.auroc, prefer: "high" } },
  { label: "Top score at the label", help: "With a single label: whether the highest score came within 100 values of it.", value: item => item.scores?.top1_hit == null ? "–" : item.scores.top1_hit ? "Yes" : "No" },
  // Near 1 the scores follow a slow level: the detector sees where the series is, not what is unusual.
  { label: "Score persistence (20 back)",
    help: "Correlation of the scores 20 values apart. Above 0.7 the detector follows the level, not what is unusual.", value: item => {
    const value = item.scores?.score_autocorrelation;
    return value == null ? "–" : `${value.toFixed(2)}${value > 0.7 ? " · follows the level" : ""}`;
  } },
  // Without labels: what the scores and alarms say about the run itself.
  { label: "Separate alarms per day", key: true, help: "Alarm episodes per day, with or without labels.", value: item => formatPerDay(item.diagnostics?.episodes_per_day) },
  { label: "Score trend over the run", help: "Rank correlation of the scores with time.", value: item => {
    const value = item.diagnostics?.score_trend;
    return value == null ? "–" : value.toFixed(2);
  } },
  { label: "Scores follow an input", help: "The strongest rank correlation of the scores with an input's value.", value: item => {
    const strongest = item.diagnostics?.follows?.[0];
    return strongest ? `${strongest.series} ${strongest.correlation.toFixed(2)}` : "–";
  } },
  // An alarm back within 10 results of the last one flaps around its boundary.
  { label: "Alarms back within 10 values", help: "Share of alarms that begin within 10 values of the last one. Above half, the alarm flaps.", value: item => {
    const value = item.diagnostics?.quick_returns;
    return value == null ? "–" : `${formatRate(value)}${value > 0.5 ? " · flaps" : ""}`;
  } },
  // Where designs disagree is where to look, and label, first.
  { label: "Alarms no other run raised", help: "Where the compared designs disagree: the first places worth a label.", value: item => item.diagnostics?.alarms_alone?.toLocaleString(LOCALE) ?? "–" },
  { label: "Scored from", value: item => formatInstant(item.scored_from) },
];

function bestOf(row: Row, runs: RunMetrics[]) {
  if (!row.best || runs.length < 2) return undefined;
  const { score, prefer } = row.best;
  const values = runs.map(score).filter((value): value is number => value != null);
  if (!values.length) return undefined;
  const target = prefer === "high" ? Math.max(...values) : Math.min(...values);
  // A tie favours nobody.
  return values.filter(value => value === target).length === 1 ? target : undefined;
}


const OUTCOME = { detected: "Detected", missed: "Missed", unscored: "Not scored" } as const;

/** The finished runs picked in the runs table, side by side and scored against the dataset's labels. */
export function RunComparison({ dataset, finished, chosen, labels }: {
  dataset: DatasetView; finished: RunSummary[]; chosen: string[]; labels: LabelView[];
}) {
  const chosenKey = chosen.join(",");
  const labelsKey = labels.map(label => `${label.id}:${label.start_at}:${label.end_at}`).join(",");
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  const [everything, setEverything] = useState(false);
  useEffect(() => {
    if (!chosenKey) return;
    const controller = new AbortController();
    dojoApi.compare(dataset.id, chosenKey.split(","), controller.signal)
      .then(result => { if (!controller.signal.aborted) { setComparison(result); setError(""); } })
      .catch(reason => { if (!controller.signal.aborted) setError(getErrorMessage(reason)); });
    return () => controller.abort();
  }, [dataset.id, chosenKey, labelsKey]);
  const { resolvedTheme, colors } = useChartColors();
  const series = useMemo(() => dataset.series.slice(0, CHART_SERIES), [dataset.series]);
  const points = useSeriesPoints(dataset.id, series);
  const alarms = useRunAlarms(chosen);
  const names = useMemo(() => new Map(finished.map(run => [run.id, runName(run)])), [finished]);
  const option = useMemo(() => datasetChartOption({
    series: series.flatMap(item => points.loaded[item.id]
      ? [{ id: item.id, name: item.name, unit: item.unit, points: points.loaded[item.id]!.points }] : []),
    labels: labels.map(label => ({ id: label.id, start: epochMilliseconds(label.start_at), end: epochMilliseconds(label.end_at), note: label.note })),
    alarms: chosen.flatMap(id => alarms.loaded[id] ? [{ id, name: names.get(id) ?? id, times: alarms.loaded[id]!.times }] : []),
    colors, timeZone,
  }), [series, points.loaded, labels, chosen, alarms.loaded, names, colors]);

  if (!finished.length) return null;
  if (!chosen.length) return <p className="dj-help">Tick finished runs to compare them.</p>;
  const shown = comparison && comparison.runs.map(item => item.run_id).join(",") === chosenKey ? comparison : null;
  const rows = everything ? ROWS : ROWS.filter(row => row.key);
  return <><div className="dj-section" role="region" aria-label="Comparison">
    <div className="dj-section-head"><h2>Comparison <span className="dj-muted">{chosen.length} of at most {DOJO_LIMITS.comparedRuns} runs</span></h2></div>
    {!labels.length && <p className="ex-banner" role="status">This dataset has no labels yet, so every alarm counts as a false
      alarm. Mark the known problems on the Labels tab first.</p>}
    {(error || points.error || alarms.error) && <p className="ex-banner ex-error" role="alert">{error || points.error || alarms.error}</p>}
    <div style={{ "--dj-alarm-rows": chosen.length } as CSSProperties}>
      <EChart option={option} resolvedTheme={resolvedTheme} className="dj-chart dj-chart--alarms"
        accessibleDescription={`Values with labels and the alarms of ${chosen.length} runs`} />
      <ChartKey entries={[...labels.length ? [{ kind: "label" as const, label: "Label", color: colors.foreground }] : [],
        { kind: "alarm-bar", label: "Alarm", color: colors.alarmBoundary }]} /></div>
    {shown && <>
      <div className="dj-table-scroll dj-section"><table className="dj-table" aria-label="Run metrics">
        <thead><tr><th>Metric</th>{shown.runs.map(item => <th key={item.run_id} className="dj-num">{names.get(item.run_id) ?? item.run_name}</th>)}</tr></thead>
        <tbody>{rows.map(row => {
          const best = bestOf(row, shown.runs);
          return <tr key={row.label}><td>{row.help ? <span className="dj-metric-name" title={row.help}>{row.label}</span> : row.label}</td>
            {shown.runs.map(item => {
              const isBest = best !== undefined && row.best?.score(item) === best;
              return <td key={item.run_id} className={isBest ? "dj-num dj-metric-best" : "dj-num"}>{row.value(item)}</td>;
            })}</tr>;
        })}</tbody>
      </table></div>
      <button type="button" className="dj-link dj-metrics-toggle" aria-expanded={everything} onClick={() => setEverything(open => !open)}>
        {everything ? "Key metrics only" : `All metrics (${ROWS.length})`}</button>
      {everything && <p className="dj-help">The best value of a metric is bold. Point at a metric's name for what it measures.</p>}
      {shown.labels.length > 0 && <div className="dj-table-scroll dj-section"><table className="dj-table" aria-label="Label outcomes">
        <thead><tr><th>Label</th>{shown.runs.map(item => <th key={item.run_id}>{names.get(item.run_id) ?? item.run_name}</th>)}</tr></thead>
        <tbody>{shown.labels.map((label, index) => <tr key={label.id}>
          <td>{formatInstant(label.start_at)} – {formatInstant(label.end_at)}{label.note && <small>{label.note}</small>}</td>
          {shown.runs.map(item => {
            const outcome = item.labels[index]!;
            return <td key={item.run_id}><span className={`dj-outcome dj-outcome--${outcome.outcome}`}>{OUTCOME[outcome.outcome]}</span>
              {outcome.delay_seconds != null && <small>after {formatDuration(outcome.delay_seconds)}</small>}</td>;
          })}
        </tr>)}</tbody>
      </table></div>}
      {shown.runs.some(item => item.diagnostics?.findings?.length) && <div className="dj-section">
        <h3>Without labels</h3>
        {shown.runs.filter(item => item.diagnostics?.findings?.length).map(item => <div key={item.run_id}>
          <h4>{names.get(item.run_id) ?? item.run_name}</h4>
          <ul aria-label={`Findings for ${names.get(item.run_id) ?? item.run_name}`}>
            {(item.diagnostics?.findings ?? []).map(finding => <li key={finding}>{finding}</li>)}</ul>
        </div>)}
      </div>}
    </>}
  </div>
  <MethodsPanel runs={finished} labelsKey={labelsKey} /></>;
}
