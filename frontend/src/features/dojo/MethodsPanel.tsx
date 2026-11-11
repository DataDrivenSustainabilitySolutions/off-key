import { useEffect, useMemo, useState } from "react";
import { getErrorMessage } from "@/lib/errors";
import type { MethodComparison, MethodMetrics, RunSummary } from "@/types/dojo.generated";
import { dojoApi } from "./api";
import { formatDuration, formatInstant, formatPerDay, formatRate, formatShare, rankMethods, runName } from "./model";

const FAMILY = { fixed: "Fixed", conformal: "Conformal", bayesian: "Bayesian" } as const;

type Column = { label: string; value: (item: MethodMetrics) => string;
  best?: { score: (item: MethodMetrics) => number | null; prefer: "high" | "low" } };

const COLUMNS: Column[] = [
  { label: "Labels detected", value: item => `${item.labels_detected} of ${item.labels_scored}` },
  { label: "Detection rate", value: item => formatRate(item.detection_rate),
    best: { score: item => item.detection_rate, prefer: "high" } },
  { label: "Median delay", value: item => formatDuration(item.median_delay_seconds),
    best: { score: item => item.median_delay_seconds, prefer: "low" } },
  { label: "False alarms", value: item => item.false_alarms.toLocaleString() },
  { label: "False alarms per day", value: item => formatPerDay(item.false_alarms_per_day),
    best: { score: item => item.false_alarms_per_day, prefer: "low" } },
  { label: "Results with an alarm", value: item => formatShare(item.alarm_share) },
];

/** The best value of a column, unless methods share it: a tie favours nobody. */
function bestOf(column: Column, methods: MethodMetrics[]) {
  if (!column.best) return undefined;
  const { score, prefer } = column.best;
  const values = methods.filter(item => !item.failed).map(score).filter((value): value is number => value != null);
  if (values.length < 2) return undefined;
  const target = prefer === "high" ? Math.max(...values) : Math.min(...values);
  return values.filter(value => value === target).length === 1 ? target : undefined;
}

/** The calibration methods one run also tried on its own scores, ranked against the dataset's labels. */
export function MethodsPanel({ runs, labelsKey }: { runs: RunSummary[]; labelsKey: string }) {
  const compared = useMemo(() => runs.filter(run => run.compares_calibration), [runs]);
  const [picked, setPicked] = useState("");
  const runId = compared.some(run => run.id === picked) ? picked : compared[0]?.id ?? "";
  const [comparison, setComparison] = useState<MethodComparison | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    dojoApi.calibration(runId, controller.signal)
      .then(result => { if (!controller.signal.aborted) { setComparison(result); setError(""); } })
      .catch(reason => { if (!controller.signal.aborted) setError(getErrorMessage(reason)); });
    return () => controller.abort();
  }, [runId, labelsKey]);
  const shown = comparison?.run_id === runId ? comparison : null;
  const methods = useMemo(() => shown ? rankMethods(shown.methods) : [], [shown]);

  return <div className="dj-section">
    <div className="dj-section-head dj-section-head--spaced"><h2>Calibration methods</h2>
      {compared.length > 1 && <label className="dj-muted">Run{" "}
        <select value={runId} aria-label="Run whose calibration methods are compared" onChange={event => setPicked(event.target.value)}>
          {compared.map(run => <option key={run.id} value={run.id}>{runName(run)}</option>)}
        </select></label>}
    </div>
    {!compared.length && <p className="dj-help">No finished run has compared calibration methods yet. Tick “Compare calibration
      methods” when you start a run to see how the fixed split and the methods that adapt would have done on its scores.</p>}
    {error && <p className="ex-banner ex-error" role="alert">{error}</p>}
    {shown && <>
      <p className="dj-help">{compared.length === 1 && `${runName(compared[0]!)}: `}every method judged the same{" "}
        {shown.results.toLocaleString()} results from {formatInstant(shown.scored_from)}, aiming at an alarm rate
        of {formatShare(shown.alpha)}{shown.consecutive > 1
          && ` and alarming after ${shown.consecutive} scores in a row above its boundary`}. Best first: most labels detected,
        then fewest false alarms per day, then the shortest delay.</p>
      <div className="dj-table-scroll"><table className="dj-table" aria-label="Calibration methods">
        <thead><tr><th>Method</th>{COLUMNS.map(column => <th key={column.label}>{column.label}</th>)}</tr></thead>
        <tbody>{methods.map(item => <tr key={item.method}>
          <td>{item.name}{item.own && <span className="dj-method-own">This run</span>}
            <small>{FAMILY[item.family]}{item.failed && ` · stopped early: ${item.failed}`}</small></td>
          {COLUMNS.map(column => {
            const best = bestOf(column, methods);
            const isBest = best !== undefined && !item.failed && column.best?.score(item) === best;
            return <td key={column.label} className={isBest ? "dj-metric-best" : undefined}>{column.value(item)}</td>;
          })}
        </tr>)}</tbody>
      </table></div>
      <p className="dj-help">The row marked “This run” is the design's own calibration step with its settings. Every other
        method saw the same detector scores with its default settings, so the table shows what changing the step alone would
        do. A method that keeps adapting also gets used to a lasting anomaly, which can end an alarm early.</p>
    </>}
  </div>;
}
