import { useState } from "react";
import { Play } from "lucide-react";
import { useConfirm } from "@/hooks/use-confirm";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetView, RunSummary } from "@/types/dojo.generated";
import { dojoApi } from "./api";
import { RunCreateDialog } from "./RunCreateDialog";
import { formatInstant, isActive, runName, runState, strategyLabel } from "./model";

export function RunsPanel({ dataset, runs, onRunsChange }: {
  dataset: DatasetView; runs: RunSummary[]; onRunsChange: () => Promise<void>;
}) {
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [confirm, confirmation] = useConfirm();
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
      <RunCreateDialog open={creating} dataset={dataset} onOpenChange={setCreating} onCreated={() => void onRunsChange()}
        trigger={<button type="button" className="dj-primary"><Play size={16} aria-hidden="true" />New run</button>} />
    </div>
    {error && <p className="dj-error" role="alert">{error}</p>}
    {runs.length > 0 && <p className="dj-help">Replay outputs include learning and calibration. Open Compare to see each run’s scored interval and detection metrics.</p>}
    {runs.length === 0 ? <p className="dj-help">No runs yet. Start one to see how a design does on this data.</p>
      : <table className="dj-table dj-record-table" role="table" aria-label="Runs">
        <thead role="rowgroup"><tr role="row">{["Run", "Status", "Replay outputs", "Alarms", "Started", "Actions"].map(label =>
          <th key={label} scope="col" role="columnheader">{label === "Actions" ? <span className="ex-sr-only">{label}</span> : label}</th>)}</tr></thead>
        <tbody role="rowgroup">{runs.map(run => {
          const state = runState(run);
          return <tr key={run.id} role="row">
            <th className="dj-record-name" scope="row" role="rowheader">{runName(run)}<small>{strategyLabel(run.strategy)}</small></th>
            <td role="cell"><span className="dj-cell-label" aria-hidden="true">Status</span>
              <span className={`mn-state mn-state--${state.tone}`}>{state.label}</span>
              {run.error && <small title={run.error}>{run.error}</small>}</td>
            <td role="cell"><span className="dj-cell-label" aria-hidden="true">Replay outputs</span>
              {run.result_count.toLocaleString()}<small>{run.points_read.toLocaleString()} of {run.points_total.toLocaleString()} values</small></td>
            <td role="cell"><span className="dj-cell-label" aria-hidden="true">Alarms</span>{run.alarm_count.toLocaleString()}</td>
            <td role="cell"><span className="dj-cell-label" aria-hidden="true">Started</span>{formatInstant(run.started_at ?? run.created_at)}</td>
            <td role="cell" className="dj-record-actions"><div className="dj-row-actions">
              {isActive(run)
                ? <button type="button" className="dj-link" disabled={busy === run.id}
                  onClick={() => void act(run, () => dojoApi.cancelRun(run.id))}>Cancel</button>
                : <button type="button" className="dj-danger" disabled={busy === run.id}
                  onClick={() => void remove(run)}>Delete</button>}
            </div></td>
          </tr>;
        })}</tbody>
      </table>}
    {confirmation}
  </div>;
}
