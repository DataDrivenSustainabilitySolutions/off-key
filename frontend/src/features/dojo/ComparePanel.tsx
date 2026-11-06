import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { getErrorMessage } from "@/lib/errors";
import type { Comparison, DatasetView, LabelView, RunMetrics, RunSummary } from "@/types/dojo.generated";
import { DOJO_LIMITS } from "@/types/dojo.generated";
import { dojoApi } from "./api";
import { DojoChart } from "./DojoChart";
import type { DojoChartData } from "./dojo-chart";
import { useRunAlarms, useSeriesPoints } from "./hooks";
import { formatDuration, formatInstant, formatPerDay, formatRate, runName } from "./model";

const CHART_SERIES = 2;

type Row = {
  label: string;
  value: (metrics: RunMetrics) => string;
  /** Lower or higher is better; the best run is shown in bold. */
  best?: { score: (metrics: RunMetrics) => number | null | undefined; prefer: "high" | "low" };
};

const ROWS: Row[] = [
  { label: "Labels detected", value: item => `${item.labels_detected} of ${item.labels_scored}`,
    best: { score: item => item.labels_detected, prefer: "high" } },
  { label: "Detection rate", value: item => formatRate(item.detection_rate),
    best: { score: item => item.detection_rate, prefer: "high" } },
  { label: "Median delay", value: item => formatDuration(item.median_delay_seconds),
    best: { score: item => item.median_delay_seconds, prefer: "low" } },
  { label: "Longest delay", value: item => formatDuration(item.max_delay_seconds) },
  { label: "False alarms", value: item => item.false_alarms.toLocaleString(),
    best: { score: item => item.false_alarms, prefer: "low" } },
  { label: "False alarms per day", value: item => formatPerDay(item.false_alarms_per_day),
    best: { score: item => item.false_alarms_per_day, prefer: "low" } },
  { label: "Time outside labels", value: item => formatDuration(item.evaluated_seconds) },
  { label: "Scored from", value: item => formatInstant(item.scored_from) },
];

function bestOf(row: Row, runs: RunMetrics[]) {
  if (!row.best || runs.length < 2) return undefined;
  const { score, prefer } = row.best;
  const values = runs.filter(run => run.scored_from != null).map(score).filter((value): value is number => value != null);
  if (values.length < 2) return undefined;
  const target = prefer === "high" ? Math.max(...values) : Math.min(...values);
  // A tie favours nobody.
  return values.filter(value => value === target).length === 1 ? target : undefined;
}

const OUTCOME = { detected: "Detected", missed: "Missed", unscored: "Not scored" } as const;

function ComparisonScroll({ label, children }: { label: string; children: ReactNode }) {
  const content = useRef<HTMLDivElement>(null);
  const [overflow, setOverflow] = useState(false);
  const hint = useId();
  useEffect(() => {
    const element = content.current;
    if (!element) return;
    const measure = () => setOverflow(element.scrollWidth > element.clientWidth + 1);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    if (element.firstElementChild) observer.observe(element.firstElementChild);
    return () => observer.disconnect();
  }, []);
  return <div className="dj-section">
    {overflow && <p className="dj-help dj-scroll-hint" id={hint}>Scroll sideways to see all runs.</p>}
    <div className="dj-table-scroll" ref={content} role="region" aria-label={label}
      aria-describedby={overflow ? hint : undefined} tabIndex={overflow ? 0 : undefined}>{children}</div>
  </div>;
}

/** Up to three finished runs side by side, scored against the dataset's labels. */
export function ComparePanel({ dataset, runs, labels }: { dataset: DatasetView; runs: RunSummary[]; labels: LabelView[] }) {
  const finished = useMemo(() => runs.filter(run => run.status === "succeeded"), [runs]);
  const [picked, setPicked] = useState<string[] | null>(null);
  const chosen = useMemo(() => (picked ?? finished.slice(0, DOJO_LIMITS.comparedRuns).map(run => run.id))
    .filter(id => finished.some(run => run.id === id)), [picked, finished]);
  const chosenKey = chosen.join(",");
  const labelsKey = labels.map(label => `${label.id}:${label.start_at}:${label.end_at}`).join(",");
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!chosenKey) return;
    const controller = new AbortController();
    dojoApi.compare(dataset.id, chosenKey.split(","), controller.signal)
      .then(result => { if (!controller.signal.aborted) { setComparison(result); setError(""); } })
      .catch(reason => { if (!controller.signal.aborted) setError(getErrorMessage(reason)); });
    return () => controller.abort();
  }, [dataset.id, chosenKey, labelsKey]);
  const series = useMemo(() => dataset.series.slice(0, CHART_SERIES), [dataset.series]);
  const points = useSeriesPoints(dataset.id, series);
  const alarms = useRunAlarms(chosen);
  const names = useMemo(() => new Map(finished.map(run => [run.id, runName(run)])), [finished]);
  const chart = useMemo<DojoChartData>(() => ({
    series: series.flatMap(item => points.loaded[item.id]
      ? [{ id: item.id, name: item.name, unit: item.unit, points: points.loaded[item.id]!.points }] : []),
    labels: labels.map(label => ({ id: label.id, start: Date.parse(label.start_at), end: Date.parse(label.end_at), note: label.note })),
    alarms: chosen.flatMap(id => alarms.loaded[id] ? [{ id, name: names.get(id) ?? id, times: alarms.loaded[id]!.times }] : []),
  }), [series, points.loaded, labels, chosen, alarms.loaded, names]);

  if (!finished.length) return <div className="dj-section"><p className="dj-help">Comparisons need finished runs. Start a run
    from the Runs tab; it appears here once it has finished.</p></div>;
  const shown = comparison && comparison.runs.map(item => item.run_id).join(",") === chosenKey ? comparison : null;
  const unscoredRuns = shown?.runs.filter(item => item.scored_from == null) ?? [];
  return <div className="dj-section">
    <div className="dj-compare-picker" role="group" aria-label={`Runs to compare, at most ${DOJO_LIMITS.comparedRuns}`}>
      {finished.map(run => {
        const checked = chosen.includes(run.id);
        return <label key={run.id}><input type="checkbox" checked={checked}
          disabled={!checked && chosen.length >= DOJO_LIMITS.comparedRuns}
          onChange={event => setPicked(event.target.checked ? [...chosen, run.id] : chosen.filter(id => id !== run.id))} />
          {runName(run)}</label>;
      })}
    </div>
    {!labels.length && <p className="ex-banner" role="status">This dataset has no labels yet, so every alarm counts as a false
      alarm. Mark the known problems on the Values tab first.</p>}
    {unscoredRuns.length > 0 && <p className="ex-banner dj-score-notice" role="status">
      <strong>{unscoredRuns.length === shown?.runs.length ? "No values scored" : "Some runs have no scores"}</strong>
      <span>{unscoredRuns.map(run => names.get(run.run_id) ?? run.run_name).join(", ")} finished without a scored interval. Metrics are unavailable for {unscoredRuns.length === 1 ? "this run" : "these runs"}.</span>
    </p>}
    {(error || points.error || alarms.error) && <p className="ex-banner ex-error" role="alert">{error || points.error || alarms.error}</p>}
    {!chosen.length && <p className="dj-help">Select at least one finished run to see its results.</p>}
    {chosen.length > 0 && dataset.series.length > CHART_SERIES && <p className="dj-help">
      The comparison chart shows {series.map(item => item.name).join(" and ")}. View the other series in Values and labels.
    </p>}
    {chosen.length > 0 && <DojoChart data={chart} description={`Values with labels and the alarms of ${chosen.length} runs`} />}
    {shown && <>
      <ComparisonScroll label="Run metrics">
        <table className="dj-table dj-comparison-table" aria-label="Run metrics">
        <thead><tr><th scope="col">Metric</th>{shown.runs.map(item => <th scope="col" key={item.run_id}>{names.get(item.run_id) ?? item.run_name}</th>)}</tr></thead>
        <tbody>{ROWS.map(row => {
          const best = bestOf(row, shown.runs);
          return <tr key={row.label}><th scope="row">{row.label}</th>{shown.runs.map(item => {
            const isBest = best !== undefined && row.best?.score(item) === best;
            return <td key={item.run_id} className={isBest ? "dj-metric-best" : undefined}>{item.scored_from ? row.value(item) : "—"}</td>;
          })}</tr>;
        })}</tbody>
      </table></ComparisonScroll>
      {shown.labels.length > 0 && <ComparisonScroll label="Label outcomes">
        <table className="dj-table dj-comparison-table" aria-label="Label outcomes">
        <thead><tr><th scope="col">Label</th>{shown.runs.map(item => <th scope="col" key={item.run_id}>{names.get(item.run_id) ?? item.run_name}</th>)}</tr></thead>
        <tbody>{shown.labels.map((label, index) => <tr key={label.id}>
          <th scope="row">{formatInstant(label.start_at)} – {formatInstant(label.end_at)}{label.note && <small>{label.note}</small>}</th>
          {shown.runs.map(item => {
            const outcome = item.labels[index]!;
            return <td key={item.run_id}><span className={`dj-outcome dj-outcome--${outcome.outcome}`}>{OUTCOME[outcome.outcome]}</span>
              {outcome.delay_seconds != null && <small>after {formatDuration(outcome.delay_seconds)}</small>}</td>;
          })}
        </tr>)}</tbody>
      </table></ComparisonScroll>}
      <p className="dj-help">A label counts as detected when the run alarmed inside it. Each alarm that begins outside every
        label is one false alarm, so an alarm held for many values counts once. Labels before the first score are not scored.</p>
    </>}
  </div>;
}
