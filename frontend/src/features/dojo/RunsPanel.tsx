import { useState } from "react";
import { Play } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { useConfirm } from "@/hooks/use-confirm";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetView, RunSummary } from "@/types/dojo.generated";
import { dojoApi } from "./api";
import { PromoteRunDialog } from "./PromoteRunDialog";
import { RunCreateDialog } from "./RunCreateDialog";
import { formatInstant, isActive, resultKindLabel, runName, runState } from "./model";

export function RunsPanel({ dataset, runs, onRunsChange }: {
  dataset: DatasetView; runs: RunSummary[]; onRunsChange: () => Promise<void>;
}) {
  const { can } = useAuth();
  const [creating, setCreating] = useState(false);
  const [promoting, setPromoting] = useState<RunSummary | null>(null);
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
      <button type="button" className="dj-primary" onClick={() => setCreating(true)}><Play size={15} />New run</button>
    </div>
    {error && <p className="dj-error" role="alert">{error}</p>}
    {runs.length === 0 ? <p className="dj-help">No runs yet. Start one to see how a design does on this data.</p>
      : <div className="dj-table-scroll"><table className="dj-table" aria-label="Runs">
        <thead><tr><th>Run</th><th>Status</th><th>Results</th><th>Alarms</th><th>Started</th><th><span className="ex-sr-only">Actions</span></th></tr></thead>
        <tbody>{runs.map(run => {
          const state = runState(run);
          return <tr key={run.id}>
            <td>{runName(run)}<small>{resultKindLabel(run.strategy)}</small></td>
            <td><span className={`mn-state mn-state--${state.tone}`}>{state.label}</span>
              {run.error && <small title={run.error}>{run.error}</small>}</td>
            <td>{run.result_count.toLocaleString()}<small>{run.points_read.toLocaleString()} of {run.points_total.toLocaleString()} values</small></td>
            <td>{run.alarm_count.toLocaleString()}</td>
            <td>{formatInstant(run.started_at ?? run.created_at)}</td>
            <td><div className="dj-row-actions">
              {run.status === "succeeded" && can("manage_monitors") && <button type="button" className="dj-link"
                disabled={busy === run.id} onClick={() => setPromoting(run)}>Use as template</button>}
              {isActive(run)
                ? <button type="button" className="dj-link" disabled={busy === run.id}
                  onClick={() => void act(run, () => dojoApi.cancelRun(run.id))}>Cancel</button>
                : <button type="button" className="dj-danger" disabled={busy === run.id}
                  onClick={() => void remove(run)}>Delete</button>}
            </div></td>
          </tr>;
        })}</tbody>
      </table></div>}
    <PromoteRunDialog run={promoting} onOpenChange={open => { if (!open) setPromoting(null); }} />
    <RunCreateDialog open={creating} dataset={dataset} onOpenChange={setCreating} onCreated={() => void onRunsChange()} />
    {confirmation}
  </div>;
}
