import { epochMilliseconds } from "@/lib/timestamps";
import { useState } from "react";
import { Check, Filter, X } from "lucide-react";
import type { DatasetView, LabelView, PendingLabelView } from "@/types/dojo.generated";
import { formatInstant } from "./model";

const overlaps = (item: PendingLabelView, label: LabelView) =>
  epochMilliseconds(item.start_at) < epochMilliseconds(label.end_at)
  && epochMilliseconds(label.start_at) < epochMilliseconds(item.end_at);

/** A series' name as a condition writes it: bare when it can be, otherwise between backticks. */
function conditionName(name: string) {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(name) && !["and", "or", "not"].includes(name) ? name : `\`${name}\``;
}

/** Who proposed a pending label: an agent by its name, or a member. */
function proposer(item: Pick<PendingLabelView, "created_by" | "created_by_agent">, userId: number | null) {
  if (item.created_by_agent) return item.created_by_agent;
  return item.created_by != null && item.created_by === userId ? "you" : "a member";
}

export type RuleRequest = { condition: string; minMinutes: number; joinMinutes: number; note: string };

/** Labels proposed by a rule or by an agent, waiting for a member to add or dismiss them.
 *
 * A pending label scores no run. One that overlaps a label is left out of the list, since labels may not overlap.
 */
export function PendingLabels({ dataset, labels, pending, userId, editable, busy, onRule, onAdd, onAdjust, onDismiss }: {
  dataset: DatasetView; labels: LabelView[]; pending: PendingLabelView[]; userId: number | null; editable: boolean;
  busy: boolean;
  /** Propose a label for every interval where the condition holds; resolves to what it found, or null when refused. */
  onRule: (request: RuleRequest) => Promise<string | null>;
  onAdd: (items: PendingLabelView[]) => void;
  /** Put a pending label into the label form to change it before adding. */
  onAdjust: (item: PendingLabelView) => void;
  onDismiss: (items: PendingLabelView[]) => void;
}) {
  const [condition, setCondition] = useState("");
  const [minMinutes, setMinMinutes] = useState("0");
  const [joinMinutes, setJoinMinutes] = useState("0");
  const [note, setNote] = useState("");
  const [found, setFound] = useState("");
  const open = pending.filter(item => !labels.some(label => overlaps(item, label)));
  const covered = pending.length - open.length;
  if (!editable && pending.length === 0) return null;
  const minutes = (value: string) => Math.max(0, Number(value) || 0);
  const names = dataset.series.map(item => conditionName(item.name));
  return <section className="dj-suggestions" aria-label="Proposed labels">
    <div className="dj-section-head dj-section-head--spaced">
      <h2>Proposed labels <span className="dj-muted">{pending.length ? `${open.length} waiting` : ""}</span></h2>
      {editable && pending.length > 1 && <span className="dj-suggestion-actions">
        <button type="button" className="dj-action" disabled={busy} onClick={() => onDismiss(pending)}><X size={15} />Dismiss all</button>
        {open.length > 1 && <button type="button" className="dj-action" disabled={busy} onClick={() => onAdd(open)}>
          <Check size={15} />Add all as labels</button>}
      </span>}
    </div>
    <p className="dj-help">Label everything where a condition holds, then check what it found before you add it. Agents
      propose labels here too. Proposed labels score no run until they are added.</p>
    {editable && <form className="dj-label-form" onSubmit={async event => {
      event.preventDefault();
      setFound("");
      const said = await onRule({ condition: condition.trim(), minMinutes: minutes(minMinutes),
        joinMinutes: minutes(joinMinutes), note: note.trim() });
      if (said !== null) { setFound(said); setNote(""); }
    }}>
      <label className="dj-field dj-field--grow"><span>Condition</span><input required maxLength={512} value={condition}
        disabled={busy} spellCheck={false} placeholder={names.length > 1 ? `${names[0]} > 10 and ${names[1]} < 5` : `${names[0] ?? "value"} > 10`}
        onChange={event => setCondition(event.target.value)} /></label>
      <label className="dj-field">At least (min)<input type="number" min={0} step="any" value={minMinutes} disabled={busy}
        onChange={event => setMinMinutes(event.target.value)} /></label>
      <label className="dj-field">Join gaps under (min)<input type="number" min={0} step="any" value={joinMinutes} disabled={busy}
        onChange={event => setJoinMinutes(event.target.value)} /></label>
      <label className="dj-field"><span>What it marks <small>(optional)</small></span><input maxLength={500} value={note}
        disabled={busy} placeholder="Overheating" onChange={event => setNote(event.target.value)} /></label>
      <button type="submit" className="dj-primary" disabled={busy || !condition.trim()}><Filter size={15} />Find intervals</button>
    </form>}
    {editable && <p className="dj-help">Series: {names.join(", ")}. Combine comparisons with and, or and not, as in a Gate
      step. Each series keeps its last value until its next one.</p>}
    {found && <p className="dj-help" role="status">{found}</p>}
    {open.length > 0 && <ul className="dj-labels dj-suggestion-list" aria-label="Pending labels">{open.map(item =>
      <li key={item.id}>
        <span>{formatInstant(item.start_at)} – {formatInstant(item.end_at)}</span>
        <span className="dj-muted">{item.note ? `${item.note} · ` : ""}by {proposer(item, userId)}
          {item.rule ? <>: <code>{item.rule}</code></> : null}</span>
        {editable && <span className="dj-suggestion-actions">
          <button type="button" className="dj-action" disabled={busy} onClick={() => onDismiss([item])}>Dismiss</button>
          <button type="button" className="dj-action" disabled={busy} onClick={() => onAdjust(item)}>Adjust</button>
          <button type="button" className="dj-action" disabled={busy} onClick={() => onAdd([item])}>Add as label</button>
        </span>}
      </li>)}</ul>}
    {covered > 0 && <p className="dj-help">{covered === 1 ? "One more overlaps" : `${covered} more overlap`} a label
      already.</p>}
  </section>;
}
