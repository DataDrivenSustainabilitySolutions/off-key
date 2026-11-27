import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Play } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { useConfirm } from "@/hooks/use-confirm";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetView, LabelView, RunSummary } from "@/types/dojo.generated";
import { DOJO_LIMITS } from "@/types/dojo.generated";
import { dojoApi } from "./api";
import { PromoteRunDialog } from "./PromoteRunDialog";
import { RunComparison } from "./RunComparison";
import { RunCreateDialog } from "./RunCreateDialog";
import { formatInstant, isActive, resultKindLabel, runName, runState } from "./model";
import { LOCALE } from "@/lib/locale";

/** Finished runs ticked for comparison when the tab opens; more can join up to the limit. */
const FIRST_PICKED = 3;

/** The dataset's runs, and the finished ones ticked side by side below them. */
export function RunsPanel({ dataset, runs, labels, current, more, onRunsChange }: {
  dataset: DatasetView; runs: RunSummary[]; labels: LabelView[]; onRunsChange: () => Promise<void>;
  /** Loads older runs, under the table. */
  more?: ReactNode;
  /** The run a link pointed to: marked and scrolled to once it is listed. */
  current?: string;
}) {
  const currentRow = useRef<HTMLTableRowElement>(null);
  const listed = runs.some(run => run.id === current);
  useEffect(() => {
    if (listed) currentRow.current?.scrollIntoView?.({ block: "center" });
  }, [listed]);
  const { can } = useAuth();
  const [creating, setCreating] = useState(false);
  const [promoting, setPromoting] = useState<RunSummary | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [confirm, confirmation] = useConfirm();
  const finished = useMemo(() => runs.filter(run => run.status === "succeeded"), [runs]);
  const [picked, setPicked] = useState<string[] | null>(null);
  const chosen = useMemo(() => (picked ?? finished.slice(0, Math.min(FIRST_PICKED, DOJO_LIMITS.comparedRuns)).map(run => run.id))
    .filter(id => finished.some(run => run.id === id)), [picked, finished]);
  const act = async (run: RunSummary, action: () => Promise<unknown>) => {
    setBusy(run.id); setError("");
    try { await action(); await onRunsChange(); }
    catch (reason) { setError(getErrorMessage(reason)); }
    finally { setBusy(null); }
  };
  const remove = async (run: RunSummary) => {
    if (!await confirm({ title: `Delete ${runName(run)}?`, description: "Its results go with it. This cannot be undone.",
      confirmLabel: "Delete run", destructive: true })) return;
    await act(run, () => dojoApi.deleteRun(run.id));
  };
  return <div className="dj-section">
    <div className="dj-section-head">
      <h2>Runs</h2>
      {can("use_dojo") && <button type="button" className="dj-primary" onClick={() => setCreating(true)}><Play size={15} />New run</button>}
    </div>
    {error && <p className="dj-error" role="alert">{error}</p>}
    {runs.length === 0 ? <p className="dj-help">No runs yet. Start one to see how a design does on this data.</p>
      : <div className="dj-table-scroll"><table className="dj-table dj-table--stack dj-runs" aria-label="Runs">
        <thead><tr><th className="dj-fit"><span className="ex-sr-only">Compare</span></th><th>Run</th><th>Status</th><th>Results</th><th className="dj-num">Alarms</th><th>Started</th><th><span className="ex-sr-only">Actions</span></th></tr></thead>
        <tbody>{runs.map(run => {
          const state = runState(run);
          const picked = run.id === current;
          const compared = chosen.includes(run.id);
          return <tr key={run.id} ref={picked ? currentRow : undefined} className={picked ? "dj-row-current" : undefined}
            aria-current={picked ? "true" : undefined}>
            <td className="dj-fit dj-pick">{run.status === "succeeded" && <label className="dj-check-box"><input type="checkbox"
              aria-label={`Compare ${runName(run)}`} checked={compared} disabled={!compared && chosen.length >= DOJO_LIMITS.comparedRuns}
              onChange={event => setPicked(event.target.checked ? [...chosen, run.id] : chosen.filter(id => id !== run.id))} /></label>}</td>
            <td>{runName(run)}<small>{resultKindLabel(run.strategy)}{run.compares_calibration && " · compares calibration methods"}{run.created_by_agent && ` · Agent · ${run.created_by_agent}`}</small></td>
            <td className="dj-fit"><span className={`mn-state mn-state--${state.tone}`}>{state.label}</span>
              {run.error && <small title={run.error}>{run.error}</small>}</td>
            <td className="dj-fit">{run.result_count.toLocaleString(LOCALE)}<span className="dj-narrow-unit"> results</span><small>{run.points_read.toLocaleString(LOCALE)} of {run.points_total.toLocaleString(LOCALE)} values</small></td>
            <td className="dj-num dj-fit">{run.alarm_count.toLocaleString(LOCALE)}<span className="dj-narrow-unit"> alarms</span></td>
            <td className="dj-fit">{formatInstant(run.started_at ?? run.created_at)}</td>
            <td><div className="dj-row-actions">
              {run.status === "succeeded" && can("manage_monitors") && <button type="button" className="dj-link"
                disabled={busy === run.id} onClick={() => setPromoting(run)}>Use as template</button>}
              {can("use_dojo") && (isActive(run)
                ? <button type="button" className="dj-link" disabled={busy === run.id}
                  onClick={() => void act(run, () => dojoApi.cancelRun(run.id))}>Cancel</button>
                : <button type="button" className="dj-danger" disabled={busy === run.id}
                  onClick={() => void remove(run)}>Delete</button>)}
            </div></td>
          </tr>;
        })}</tbody>
      </table></div>}
    {more}
    <RunComparison dataset={dataset} finished={finished} chosen={chosen} labels={labels} />
    <PromoteRunDialog run={promoting} onOpenChange={open => { if (!open) setPromoting(null); }} />
    <RunCreateDialog open={creating} dataset={dataset} onOpenChange={setCreating} onCreated={() => void onRunsChange()} />
    {confirmation}
  </div>;
}
