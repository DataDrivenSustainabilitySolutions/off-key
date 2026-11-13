import { useEffect, useMemo, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Button } from "@/components/ui/button";
import { getErrorMessage } from "@/lib/errors";
import { loadOffsetPages } from "@/lib/offset-pages";
import type { DatasetView, RunView } from "@/types/dojo.generated";
import { pipelinesApi } from "../pipelines/api";
import type { PipelineDefinition } from "../pipelines/contracts";
import { dojoApi } from "./api";
import { comparesCalibration, suggestBindings } from "./model";

type Choice = { key: string; name: string; group: "template" | "design"; definition?: PipelineDefinition };

/** Pick a design from the templates or the library, bind its inputs to series and queue a run. */
export function RunCreateDialog({ open, dataset, onOpenChange, onCreated }: {
  open: boolean; dataset: DatasetView; onOpenChange: (open: boolean) => void; onCreated: (run: RunView) => void;
}) {
  const [choices, setChoices] = useState<Choice[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [key, setKey] = useState("");
  const [definition, setDefinition] = useState<PipelineDefinition | null>(null);
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [holdIntervals, setHoldIntervals] = useState("3");
  const [minimumHold, setMinimumHold] = useState("30");
  const [compare, setCompare] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selection = useRef<AbortController | null>(null);
  const [designPages, setDesignPages] = useState(1);
  const [moreDesigns, setMoreDesigns] = useState(false);
  const [loadingDesigns, setLoadingDesigns] = useState(true);

  useEffect(() => () => selection.current?.abort(), [open, dataset.id]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void Promise.all([pipelinesApi.catalog(controller.signal), loadOffsetPages(
      offset => pipelinesApi.list({ limit: 100, offset }, controller.signal), designPages, controller.signal,
    )])
      .then(([catalog, library]) => {
        if (controller.signal.aborted) return;
        setChoices([
          ...catalog.templates.map(item => ({ key: `template:${item.id}`, name: item.name, group: "template" as const,
            definition: item.definition })),
          ...library.items.map(item => ({ key: `design:${item.id}`, name: item.name, group: "design" as const })),
        ]);
        setMoreDesigns(library.next_offset !== null);
      })
      .catch(reason => { if (!controller.signal.aborted) setLoadError(getErrorMessage(reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoadingDesigns(false); });
    return () => controller.abort();
  }, [open, designPages]);

  const choose = async (next: string) => {
    selection.current?.abort();
    const controller = new AbortController();
    selection.current = controller;
    setKey(next); setDefinition(null); setError("");
    const choice = choices?.find(item => item.key === next);
    if (!choice) return;
    try {
      const chosen = choice.definition ?? (await pipelinesApi.get(next.slice("design:".length), controller.signal)).draft;
      if (controller.signal.aborted) return;
      setDefinition(chosen);
      setBindings(suggestBindings(chosen.input_slots, dataset.series));
      setName(choice.name);
    } catch (reason) {
      if (!controller.signal.aborted) setError(getErrorMessage(reason));
    }
  };
  const close = (next: boolean) => {
    if (!next) {
      selection.current?.abort();
      setKey(""); setDefinition(null); setError(""); setCompare(false);
      setLoadingDesigns(true); setLoadError("");
    }
    onOpenChange(next);
  };
  const slots = useMemo(() => definition?.input_slots ?? [], [definition]);
  const detectors = definition?.nodes.filter(node => node.kind === "detector").length ?? 0;
  const bound = slots.length > 0 && slots.every(slot => bindings[slot.id]);
  const duplicates = useMemo(() => {
    const values = slots.map(slot => bindings[slot.id]).filter(Boolean);
    return new Set(values).size !== values.length;
  }, [slots, bindings]);
  const alignment = { hold_intervals: Number(holdIntervals), minimum_hold_seconds: Number(minimumHold) };
  const alignmentValid = alignment.hold_intervals >= 1 && alignment.hold_intervals <= 1000
    && alignment.minimum_hold_seconds > 0 && alignment.minimum_hold_seconds <= 7 * 86400;
  const comparable = !!definition && comparesCalibration(definition);
  const submit = async () => {
    if (!definition) return;
    setBusy(true); setError("");
    try {
      const run = await dojoApi.createRun({ dataset_id: dataset.id, name: name.trim(), definition, alignment,
        bindings: Object.fromEntries(slots.map(slot => [slot.id, bindings[slot.id]!])),
        ...(compare && comparable ? { compare_calibration: true } : {}) });
      close(false);
      onCreated(run);
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  const templates = choices?.filter(item => item.group === "template") ?? [];
  const designs = choices?.filter(item => item.group === "design") ?? [];
  return <Dialog.Root open={open} onOpenChange={next => { if (!busy) close(next); }}>
    <Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" />
      <Dialog.Content className="ex-dialog dj-dialog">
        <Dialog.Title>New run</Dialog.Title>
        <Dialog.Description className="dj-help">The design runs over the whole dataset in time order, with the same
          alignment, learning and scoring as a live monitor. Nothing reaches Monitoring or Reporting.</Dialog.Description>
        <form onSubmit={event => { event.preventDefault(); if (bound && !duplicates && alignmentValid && !busy) void submit(); }}>
          {loadError && <p className="dj-error" role="alert">{loadError}</p>}
          <label className="dj-field">Design
            <select value={key} disabled={busy || !choices} onChange={event => void choose(event.target.value)}>
              <option value="" disabled>{choices ? "Choose a template or design" : "Loading designs…"}</option>
              {templates.length > 0 && <optgroup label="Templates">{templates.map(item =>
                <option key={item.key} value={item.key}>{item.name}</option>)}</optgroup>}
              {designs.length > 0 && <optgroup label="Your designs">{designs.map(item =>
                <option key={item.key} value={item.key}>{item.name}</option>)}</optgroup>}
            </select>
          </label>
          {moreDesigns && <Button type="button" variant="outline" disabled={busy || loadingDesigns}
            onClick={() => { setLoadingDesigns(true); setLoadError(""); setDesignPages(count => count + 1); }}>
            {loadingDesigns ? "Loading designs…" : "Load more designs"}</Button>}
          {definition && <>
            <p className="dj-help">{detectors} {detectors === 1 ? "detector" : "detectors"} · {slots.length} {slots.length === 1 ? "input" : "inputs"}</p>
            <fieldset className="dj-field"><legend>Inputs</legend>
              <div className="dj-bindings">{slots.map(slot => <label key={slot.id} className="dj-binding">
                <span>{slot.label}{slot.unit ? ` (${slot.unit})` : ""}</span>
                <select value={bindings[slot.id] ?? ""} disabled={busy} aria-label={`Series for ${slot.label}`}
                  onChange={event => setBindings(previous => ({ ...previous, [slot.id]: event.target.value }))}>
                  <option value="" disabled>Choose a series</option>
                  {dataset.series.map(item => <option key={item.id} value={item.id}>
                    {item.name}{item.unit ? ` (${item.unit})` : ""}</option>)}
                </select>
              </label>)}</div>
              {duplicates && <span className="dj-error">Each series can feed one input only.</span>}
            </fieldset>
            <label className="dj-field">Run name<input maxLength={120} value={name} disabled={busy}
              onChange={event => setName(event.target.value)} /></label>
            <div className="dj-field-row">
              <label className="dj-field"><span>Hold values for <small>(intervals)</small></span><input type="number" min={1} max={1000} step="any"
                value={holdIntervals} disabled={busy} onChange={event => setHoldIntervals(event.target.value)} /></label>
              <label className="dj-field"><span>But at least <small>(seconds)</small></span><input type="number" min={0.001} step="any"
                value={minimumHold} disabled={busy} onChange={event => setMinimumHold(event.target.value)} /></label>
            </div>
            <label className="dj-check"><input type="checkbox" checked={compare && comparable} disabled={busy || !comparable}
              aria-describedby="dj-compare-help" onChange={event => setCompare(event.target.checked)} />
              Compare calibration methods</label>
            <p className="dj-help" id="dj-compare-help">{comparable
              ? "Also tries the fixed split and every method that adapts on this run's scores, at the same alarm rate. The run takes longer."
              : "This design alarms on a conformal martingale, which has no boundary on scores to try other methods on."}</p>
          </>}
          {error && <p className="dj-error" role="alert">{error}</p>}
          <div className="ex-dialog-actions">
            <Button type="button" variant="outline" disabled={busy} onClick={() => close(false)}>Cancel</Button>
            <Button type="submit" disabled={busy || !bound || duplicates || !alignmentValid}>{busy ? "Queueing…" : "Start run"}</Button>
          </div>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
