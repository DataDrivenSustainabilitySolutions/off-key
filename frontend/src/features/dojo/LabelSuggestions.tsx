import { epochMilliseconds } from "@/lib/timestamps";
import { useEffect, useMemo, useState } from "react";
import { BellRing } from "lucide-react";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetView, LabelSuggestion, LabelSuggestionList, LabelView } from "@/types/dojo.generated";
import { formatInstant, suggestionNote } from "./model";

const overlaps = (item: LabelSuggestion, label: LabelView) =>
  epochMilliseconds(item.start_at) < epochMilliseconds(label.end_at)
  && epochMilliseconds(label.start_at) < epochMilliseconds(item.end_at);

/** Alarms live monitors recorded on the dataset's readings, offered as labels.
 *
 * Only datasets copied from recorded readings have alarms to offer. A suggestion that overlaps a label is
 * left out, since labels may not overlap; adding one re-reads the labels, so it drops out at once.
 */
export function LabelSuggestions({ dataset, labels, busy, load, onAdd, onAdjust }: {
  dataset: DatasetView; labels: LabelView[]; busy: boolean;
  load: (signal: AbortSignal) => Promise<LabelSuggestionList>;
  /** Add these suggestions as labels, in order. */
  onAdd: (items: LabelSuggestion[]) => void;
  /** Put a suggestion into the label form to change it before adding. */
  onAdjust: (item: LabelSuggestion) => void;
}) {
  const recorded = dataset.series.some(item => item.reading_id);
  const [found, setFound] = useState<LabelSuggestionList | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!recorded) return;
    const controller = new AbortController();
    load(controller.signal)
      .then(result => { if (!controller.signal.aborted) { setFound(result); setError(""); } })
      .catch(reason => { if (!controller.signal.aborted) setError(getErrorMessage(reason)); });
    return () => controller.abort();
  }, [recorded, load]);
  const open = useMemo(() => found?.items.filter(item => !labels.some(label => overlaps(item, label))) ?? [], [found, labels]);
  if (!recorded) return null;
  const covered = (found?.items.length ?? 0) - open.length;
  return <section className="dj-suggestions" aria-label="Recorded alarms">
    <div className="dj-section-head dj-section-head--spaced">
      <h2>Recorded alarms <span className="dj-muted">{found ? `${open.length} not labelled` : ""}</span></h2>
      {open.length > 1 && <button type="button" className="dj-action" disabled={busy} onClick={() => onAdd(open)}>
        <BellRing size={15} />Add all as labels</button>}
    </div>
    <p className="dj-help">Alarms live monitors raised on these readings during the dataset’s time span, grouped when they
      came less than ten minutes apart. They are suggestions: check them against the values before you rely on them.</p>
    {error ? <p className="dj-error" role="alert">{error}</p>
      : !found ? <p className="dj-loading" role="status">Looking for recorded alarms…</p>
      : found.items.length === 0 ? <p className="dj-help" role="status">No monitor raised an alarm on these readings during
        this time span.</p>
      : <>
        {open.length > 0 && <ul className="dj-labels dj-suggestion-list" aria-label="Suggested labels">{open.map(item =>
          <li key={item.start_at}>
            <span>{formatInstant(item.start_at)} – {formatInstant(item.end_at)}</span>
            <span className="dj-muted">{suggestionNote(item)}{item.monitor_ids.length > 1
              ? ` from ${item.monitor_ids.length} monitors` : ""}</span>
            <span className="dj-suggestion-actions">
              <button type="button" className="dj-action" disabled={busy} onClick={() => onAdjust(item)}>Adjust</button>
              <button type="button" className="dj-action" disabled={busy} onClick={() => onAdd([item])}>Add as label</button>
            </span>
          </li>)}</ul>}
        {covered > 0 && <p className="dj-help">{covered === 1 ? "One more overlaps" : `${covered} more overlap`} a label
          already.</p>}
        {found.truncated && <p className="dj-help">Only the earliest alarms are shown; copy a shorter window to see the rest.</p>}
      </>}
  </section>;
}
