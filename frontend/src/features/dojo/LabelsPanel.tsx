import { epochMilliseconds } from "@/lib/timestamps";
import { useCallback, useMemo, useState } from "react";
import { Tag, Trash2 } from "lucide-react";
import { useConfirm } from "@/hooks/use-confirm";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetView, LabelSuggestion, LabelView } from "@/types/dojo.generated";
import { DOJO_LIMITS } from "@/types/dojo.generated";
import { EChart } from "../charts/EChart";
import { useChartColors } from "../charts/use-chart-colors";
import { dojoApi } from "./api";
import { datasetChartOption } from "./dojo-chart";
import { CHART_POINTS, useSeriesPoints } from "./hooks";
import { LabelSuggestions } from "./LabelSuggestions";
import { formatInstant, fromLocalInput, suggestionNote, toLocalInput } from "./model";

const SHOWN_SERIES = 4;
const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

/** The dataset's values with its labels: zoom to a problem, then mark it. */
export function LabelsPanel({ dataset, labels, onLabelsChange }: {
  dataset: DatasetView; labels: LabelView[]; onLabelsChange: () => Promise<void>;
}) {
  const { resolvedTheme, colors } = useChartColors();
  const [shown, setShown] = useState(() => dataset.series.slice(0, SHOWN_SERIES).map(item => item.id));
  const series = useMemo(() => dataset.series.filter(item => shown.includes(item.id)), [dataset.series, shown]);
  const { loaded, error: loadError, loading } = useSeriesPoints(dataset.id, series);
  const [viewport, setViewport] = useState<[number, number] | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirm, confirmation] = useConfirm();
  const option = useMemo(() => datasetChartOption({
    series: series.flatMap(item => loaded[item.id] ? [{ id: item.id, name: item.name, unit: item.unit, points: loaded[item.id]!.points }] : []),
    labels: labels.map(label => ({ id: label.id, start: epochMilliseconds(label.start_at), end: epochMilliseconds(label.end_at), note: label.note })),
    colors, timeZone,
  }), [series, loaded, labels, colors]);
  const truncated = series.filter(item => loaded[item.id]?.truncated);
  const act = async (action: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await action(); await onLabelsChange(); return true; }
    catch (reason) { setError(getErrorMessage(reason)); return false; }
    finally { setBusy(false); }
  };
  const startAt = fromLocalInput(start), endAt = fromLocalInput(end);
  const create = async () => {
    if (!startAt || !endAt) return;
    if (await act(() => dojoApi.createLabel(dataset.id, { start_at: startAt, end_at: endAt, note: note.trim() }))) {
      setStart(""); setEnd(""); setNote("");
    }
  };
  const loadSuggestions = useCallback((signal: AbortSignal) => dojoApi.labelSuggestions(dataset.id, {}, signal), [dataset.id]);
  // All or nothing: a refused suggestion leaves the labels as they were.
  const addSuggested = (items: LabelSuggestion[]) => void act(() => dojoApi.createLabels(dataset.id, {
    labels: items.map(item => ({ start_at: item.start_at, end_at: item.end_at, note: suggestionNote(item) })) }));
  const adjust = (item: LabelSuggestion) => {
    setStart(toLocalInput(item.start_at)); setEnd(toLocalInput(item.end_at)); setNote(suggestionNote(item));
  };
  const remove = async (label: LabelView) => {
    if (!await confirm({ title: "Delete label?", description: `${formatInstant(label.start_at)} – ${formatInstant(label.end_at)}`,
      confirmLabel: "Delete", destructive: true })) return;
    await act(() => dojoApi.deleteLabel(dataset.id, label.id));
  };
  return <div className="dj-section">
    <div className="dj-series-picker" role="group" aria-label="Series shown">
      {dataset.series.map(item => <label key={item.id}><input type="checkbox" checked={shown.includes(item.id)}
        onChange={event => setShown(previous => event.target.checked ? [...previous, item.id] : previous.filter(id => id !== item.id))} />
        {item.name}{item.unit ? ` (${item.unit})` : ""}</label>)}
    </div>
    {loadError && <p className="ex-banner ex-error" role="alert">{loadError}</p>}
    {loading && <p className="dj-loading" role="status">Loading values…</p>}
    <EChart option={option} resolvedTheme={resolvedTheme} className="dj-chart"
      accessibleDescription={`Values of ${series.map(item => item.name).join(", ") || "no series"} with ${labels.length} labels`}
      onViewportChange={(from, to) => setViewport([from, to])} />
    {truncated.length > 0 && <p className="dj-help">Showing the first {CHART_POINTS.toLocaleString()} values of{" "}
      {truncated.map(item => item.name).join(", ")}. Runs and metrics always use every value.</p>}

    <div className="dj-section-head dj-section-head--spaced">
      <h2>Labels <span className="dj-muted">{labels.length} of at most {DOJO_LIMITS.labels}</span></h2>
      <button type="button" className="dj-action" disabled={!viewport || busy} onClick={() => {
        if (!viewport) return;
        setStart(toLocalInput(viewport[0])); setEnd(toLocalInput(viewport[1]));
      }}><Tag size={15} />Use the zoomed range</button>
    </div>
    <p className="dj-help">A label marks a known problem. Runs are scored against the labels when you compare them, so
      editing a label never needs a new run.</p>
    <form className="dj-label-form" onSubmit={event => { event.preventDefault(); void create(); }}>
      <label className="dj-field">From<input type="datetime-local" step={1} required value={start} disabled={busy}
        onChange={event => setStart(event.target.value)} /></label>
      <label className="dj-field">To<input type="datetime-local" step={1} required value={end} disabled={busy}
        onChange={event => setEnd(event.target.value)} /></label>
      <label className="dj-field dj-field--grow"><span>Note <small>(optional)</small></span><input maxLength={500}
        value={note} disabled={busy} placeholder="What happened" onChange={event => setNote(event.target.value)} /></label>
      <button type="submit" className="dj-primary" disabled={busy || !startAt || !endAt || endAt <= startAt}>Add label</button>
    </form>
    {error && <p className="dj-error" role="alert">{error}</p>}
    {labels.length > 0 && <ul className="dj-labels" aria-label="Labels">{labels.map(label =>
      <li key={label.id}>
        <span>{formatInstant(label.start_at)} – {formatInstant(label.end_at)}</span>
        <input aria-label="Label note" maxLength={500} defaultValue={label.note} placeholder="Add a note" disabled={busy}
          onBlur={event => {
            const value = event.target.value.trim();
            if (value !== label.note) void act(() => dojoApi.changeLabel(dataset.id, label.id, { note: value }));
          }} />
        <button type="button" className="dj-danger" disabled={busy} aria-label="Delete label"
          onClick={() => void remove(label)}><Trash2 size={14} /></button>
      </li>)}</ul>}
    <LabelSuggestions dataset={dataset} labels={labels} busy={busy} load={loadSuggestions} onAdd={addSuggested}
      onAdjust={adjust} />
    {confirmation}
  </div>;
}
