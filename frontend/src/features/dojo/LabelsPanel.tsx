import { useId, useMemo, useState } from "react";
import { Tag, Trash2 } from "lucide-react";
import { useConfirm } from "@/hooks/use-confirm";
import { getErrorMessage } from "@/lib/errors";
import { formatChartTime, getLocalTimeZone } from "../charts/telemetry-chart";
import type { DatasetView, LabelView } from "@/types/dojo.generated";
import { DOJO_LIMITS } from "@/types/dojo.generated";
import { dojoApi } from "./api";
import { DojoChart } from "./DojoChart";
import type { DojoChartData } from "./dojo-chart";
import { CHART_POINTS, useSeriesPoints } from "./hooks";
import { fromLocalInput, toLocalInput } from "./model";

const SHOWN_SERIES = 4;
const timeZone = getLocalTimeZone();
const labelInterval = (label: LabelView) =>
  `${formatChartTime(Date.parse(label.start_at), timeZone, "tooltip")} – ${formatChartTime(Date.parse(label.end_at), timeZone, "tooltip")}`;

/** The dataset's values with its labels: zoom to a problem, then mark it. */
export function LabelsPanel({ dataset, labels, onLabelsChange }: {
  dataset: DatasetView; labels: LabelView[]; onLabelsChange: () => Promise<void>;
}) {
  const [shown, setShown] = useState(() => dataset.series.slice(0, SHOWN_SERIES).map(item => item.id));
  const series = useMemo(() => dataset.series.filter(item => shown.includes(item.id)), [dataset.series, shown]);
  const { loaded, error: loadError, loading } = useSeriesPoints(dataset.id, series);
  const [viewport, setViewport] = useState<[number, number] | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const overlapMessage = useId();
  const [confirm, confirmation] = useConfirm();
  const chart = useMemo<DojoChartData>(() => ({
    series: series.flatMap(item => loaded[item.id] ? [{ id: item.id, name: item.name, unit: item.unit, points: loaded[item.id]!.points }] : []),
    labels: labels.map(label => ({ id: label.id, start: Date.parse(label.start_at), end: Date.parse(label.end_at), note: label.note })),
  }), [series, loaded, labels]);
  const truncated = series.filter(item => loaded[item.id]?.truncated);
  const act = async (action: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await action(); await onLabelsChange(); return true; }
    catch (reason) { setError(getErrorMessage(reason)); return false; }
    finally { setBusy(false); }
  };
  const startAt = fromLocalInput(start), endAt = fromLocalInput(end);
  const validRange = !!startAt && !!endAt && startAt < endAt;
  const conflict = validRange ? labels.find(label =>
    Date.parse(label.start_at) < Date.parse(endAt) && Date.parse(label.end_at) > Date.parse(startAt)) : undefined;
  const create = async () => {
    if (!validRange || conflict) return;
    if (await act(() => dojoApi.createLabel(dataset.id, { start_at: startAt, end_at: endAt, note: note.trim() }))) {
      setStart(""); setEnd(""); setNote("");
    }
  };
  const remove = async (label: LabelView) => {
    if (!await confirm({ title: "Delete label?", description: labelInterval(label),
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
    {(!loading || chart.series.length > 0) && <DojoChart data={chart} description={`Values of ${series.map(item => item.name).join(", ") || "no series"} with ${labels.length} labels`}
      onRangeChange={setViewport} />}
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
        aria-invalid={!!conflict || undefined} aria-describedby={conflict ? overlapMessage : undefined}
        onChange={event => setStart(event.target.value)} /></label>
      <label className="dj-field">To<input type="datetime-local" step={1} required value={end} disabled={busy}
        aria-invalid={!!conflict || undefined} aria-describedby={conflict ? overlapMessage : undefined}
        onChange={event => setEnd(event.target.value)} /></label>
      <label className="dj-field dj-field--grow"><span>Note <small>(optional)</small></span><input maxLength={500}
        value={note} disabled={busy} placeholder="What happened" onChange={event => setNote(event.target.value)} /></label>
      <button type="submit" className="dj-primary" disabled={busy || !validRange || !!conflict}>Add label</button>
    </form>
    {conflict && <p id={overlapMessage} className="dj-error" role="status">
      This range overlaps {conflict.note ? `“${conflict.note}” (${labelInterval(conflict)})` : labelInterval(conflict)}. Choose a time before or after it.
    </p>}
    {error && <p className="dj-error" role="alert">{error}</p>}
    {labels.length > 0 && <ul className="dj-labels" aria-label="Labels">{labels.map(label =>
      <li key={label.id}>
        <span>{labelInterval(label)}</span>
        <input aria-label={`Label note for ${labelInterval(label)}`} maxLength={500} defaultValue={label.note} placeholder="Add a note" disabled={busy}
          onBlur={event => {
            const value = event.target.value.trim();
            if (value !== label.note) void act(() => dojoApi.changeLabel(dataset.id, label.id, { note: value }));
          }} />
        <button type="button" className="dj-danger" disabled={busy} aria-label={`Delete label for ${labelInterval(label)}`}
          onClick={() => void remove(label)}><Trash2 size={14} /></button>
      </li>)}</ul>}
    {confirmation}
  </div>;
}
