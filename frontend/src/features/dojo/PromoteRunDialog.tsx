import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { getErrorMessage } from "@/lib/errors";
import type { RunPromotion, RunSummary } from "@/types/dojo.generated";
import { dojoApi } from "./api";
import { monitoringHandOff, runName } from "./model";

/** Save a run's design as a template, then continue in Monitoring with its tested inputs suggested. */
export function PromoteRunDialog({ run, onOpenChange }: {
  run: RunSummary | null; onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<RunPromotion | null>(null);
  const [opened, setOpened] = useState<string | null>(null);
  if (run && opened !== run.id) {
    setOpened(run.id); setName(runName(run)); setDescription(""); setError(""); setSaved(null);
  }
  const close = (next: boolean) => { if (!busy) onOpenChange(next); };
  const submit = async () => {
    if (!run) return;
    setBusy(true); setError("");
    try {
      setSaved(await dojoApi.promoteRun(run.id, { name: name.trim(), description }));
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  const live = saved?.bindings.filter(item => item.reading_id) ?? [];
  return <Dialog.Root open={!!run} onOpenChange={close}>
    <Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" />
      <Dialog.Content className="ex-dialog dj-dialog">
        <Dialog.Title>Use as template</Dialog.Title>
        <Dialog.Description className="dj-help">The run's design goes into the template library, ready to start a
          monitor on live readings. The run and its dataset stay as they are.</Dialog.Description>
        {saved ? <>
          <p role="status">Saved <strong>{saved.pipeline_name}</strong> to the template library.</p>
          <ul className="dj-promoted" aria-label="Inputs">{saved.bindings.map(item => <li key={item.slot_id}>
            <span>{item.slot_label}</span>
            <small>{item.reading_id ? `${item.series_name}, suggested as its recorded reading`
              : `${item.series_name} was uploaded; choose a live reading in Monitoring`}</small>
          </li>)}</ul>
          <div className="ex-dialog-actions">
            <Button type="button" variant="outline" onClick={() => close(false)}>Stay in the Dojo</Button>
            <Button type="button" onClick={() => navigate(monitoringHandOff(saved))}>
              {live.length ? "Start a monitor" : "Open in Monitoring"}</Button>
          </div>
        </> : <form onSubmit={event => { event.preventDefault(); if (name.trim() && !busy) void submit(); }}>
          <label className="dj-field">Template name<input required maxLength={120} value={name} disabled={busy}
            onChange={event => setName(event.target.value)} /></label>
          <label className="dj-field"><span>Description <small>(optional)</small></span>
            <textarea maxLength={2000} rows={3} value={description} disabled={busy}
              onChange={event => setDescription(event.target.value)} /></label>
          {error && <p className="dj-error" role="alert">{error}</p>}
          <div className="ex-dialog-actions">
            <Button type="button" variant="outline" disabled={busy} onClick={() => close(false)}>Cancel</Button>
            <Button type="submit" disabled={busy || !name.trim()}>{busy ? "Saving…" : "Save template"}</Button>
          </div>
        </form>}
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
