import { useState } from "react";
import { Button } from "@/components/ui/button";
import { originLabel, policyLabel, scopeKey, topicWithinPrefix, type RuleScope } from "@/domain/system/collectionRules";
import type { RuleEdit } from "@/domain/system/collectionRules";
import type { SystemDocument, SystemRuntime } from "@/types/system";
import type { CollectionPolicy } from "@/types/collection";
import type { Recording } from "./useRecording";
import { recordingEdit, type Choice } from "./recordingEdits";

type Props = { scope: RuleScope; ids: string[]; document: SystemDocument; runtime?: SystemRuntime;
  canEdit: boolean; recording: Recording };


export function SourceRecordingInspector({ scope, ids, document, runtime, canEdit, recording }: Props) {
  const rule = (runtime?.collection_rules ?? []).find(item => scopeKey(item.scope) === scopeKey(scope));
  const own: Choice = rule?.policy?.mode ?? "inherit";
  const stored: Choice = scope.kind === "broker" && own === "inherit" ? "off" : own;
  // The picked option stays selected while it saves or waits for the monitor confirmation.
  const [picked, setPicked] = useState<Choice>();
  const saved = rule?.policy?.interval_seconds ?? 10;
  const [interval, setIntervalText] = useState(String(saved));
  const selected = ids.flatMap(id => runtime?.bindings?.[id] ?? []);
  const enabled = selected.filter(item => item.policy.mode !== "off").length;
  // The rate is summarised over the readings that record; the checkboxes show which ones those are.
  const recorded = selected.filter(item => item.policy.mode !== "off");
  const sameRate = (left: CollectionPolicy, right: CollectionPolicy) => left.mode === right.mode
    && (left.mode !== "sample" || left.interval_seconds === right.interval_seconds);
  const uniform = recorded.length && recorded.every(item => sameRate(item.policy, recorded[0]!.policy)) ? recorded[0]!.policy : undefined;
  const excluded = ids.filter(id => runtime?.bindings?.[id]?.policy_origin?.needs_review);
  const exceptions = (runtime?.collection_rules ?? []).filter(item => item.policy && scopeKey(item.scope) !== scopeKey(scope)
    && item.scope.connection_id === scope.connection_id && (scope.kind === "broker" || scope.kind === "topic"
      && (item.scope.kind === "topic" ? topicWithinPrefix(item.scope.topic_prefix ?? "", scope.topic_prefix ?? "")
        : ids.includes(item.scope.reading_id ?? "")))).length;
  const busy = recording.saving === scope.connection_id;
  const pending = !!recording.pending && recording.pending.edits.some(edit => edit.scope.connection_id === scope.connection_id);
  const choice: Choice = (busy || pending) && picked ? picked : stored;
  const seconds = Math.round(Number(interval));
  const validInterval = Number.isFinite(seconds) && seconds >= 1 && seconds <= 3600;
  const choose = (next: Choice) => {
    if (busy || next === choice && (next !== "sample" || seconds === saved)) return;
    if (next === "sample" && !validInterval) return;
    setPicked(next);
    void recording.save([recordingEdit(scope, next, next === "sample" ? seconds : saved)]);
  };
  const commitInterval = () => {
    if (choice !== "sample") return;
    if (!validInterval) { setIntervalText(String(saved)); return; }
    if (seconds !== saved) choose("sample");
  };
  const summary = ids.length === 1
    ? selected[0] && [policyLabel(selected[0].policy), originLabel(runtime, ids[0]!, document)].filter(Boolean).join(" · ")
    : ids.length ? `${enabled} of ${ids.length} enabled${uniform ? ` · ${policyLabel(uniform)}` : enabled ? " · Mixed rates" : ""}` : "No readings";
  const collection = runtime?.collection;
  const collectionPending = (enabled > 0 || recording.canUndo(scope.connection_id)) &&
    (collection?.status !== "applied" || collection.revision !== runtime?.collection_revision);
  const collectionFailed = collection?.status === "error" || collection?.status === "disabled";
  const options: [Choice, string][] = [
    ...scope.kind === "broker" ? [] : [["inherit", "Same as above"] as [Choice, string]],
    ["off", "Off"], ["original", "Every message"], ["sample", "At intervals"],
  ];
  // Readings opt in by following this scope when it records, or with their own rule when it does not.
  const parentRecords = choice === "original" || choice === "sample";
  const readingEdit = (reading_id: string, on: boolean): RuleEdit => {
    const reading: RuleScope = { kind: "reading", connection_id: scope.connection_id, reading_id };
    return on ? parentRecords ? { scope: reading, operation: "inherit" }
      : { scope: reading, operation: "set", policy: { mode: "original", interval_seconds: saved } }
      : { scope: reading, operation: "set", policy: { mode: "off", interval_seconds: saved } };
  };
  const isOn = (id: string) => (runtime?.bindings?.[id]?.policy.mode ?? "off") !== "off";
  const toggleAll = (on: boolean) => {
    const edits = ids.filter(id => isOn(id) !== on).map(id => readingEdit(id, on));
    if (edits.length) void recording.save(edits);
  };
  /** A reading that records at a rate of its own says so next to its name. */
  const rateNote = (id: string) => {
    const policy = runtime?.bindings?.[id]?.policy;
    const parent = parentRecords ? { mode: choice as CollectionPolicy["mode"], interval_seconds: saved } : undefined;
    return policy && policy.mode !== "off" && (!parent || !sameRate(policy, parent)) ? policyLabel(policy).toLowerCase() : undefined;
  };
  const streams = new Map(document.streams.map(stream => [stream.id, stream]));
  return <section className="source-recording" aria-label="Recording configuration">
    <div className="ex-preview-section-heading"><h2>Recording</h2>{summary && <span>{summary}</span>}</div>
    {!busy && collectionPending && <p className="ex-muted" role={collectionFailed ? "alert" : "status"}>
      {collectionFailed ? "Recording settings could not be applied." : "Applying recording settings…"}
    </p>}
    {canEdit && <>
      <div className="source-recording-choice" role="radiogroup" aria-label="Recording" aria-busy={busy}>
        {options.map(([value, label]) => <div key={value} className={`source-recording-option${choice === value ? " is-selected" : ""}`}>
          <label><input type="radio" name={`recording-${scopeKey(scope)}`} value={value} checked={choice === value}
            disabled={busy} onChange={() => choose(value)} />{label}</label>
          {/* The interval sits beside its option, not inside the label, so typing in it never picks an option. */}
          {value === "sample" && <span className="source-recording-interval">
            <input aria-label="Seconds between samples" type="number" min={1} max={3600} value={interval} disabled={busy}
              onChange={event => setIntervalText(event.target.value)}
              onBlur={commitInterval} onKeyDown={event => { if (event.key === "Enter") commitInterval(); }} />s</span>}
        </div>)}
      </div>
      {busy && <p className="ex-muted" role="status">Saving…</p>}
      {scope.kind !== "reading" && ids.length > 1 && <fieldset className="source-readings" disabled={busy}>
        <legend>Readings<span>
          <button type="button" onClick={() => toggleAll(true)} disabled={enabled === ids.length}>All</button>
          <button type="button" onClick={() => toggleAll(false)} disabled={enabled === 0}>None</button></span></legend>
        {ids.map(id => <label key={id}><input type="checkbox" checked={isOn(id)}
          onChange={event => void recording.save([readingEdit(id, event.target.checked)])} />
          <span>{streams.get(id)?.label ?? id}{rateNote(id) && <em> · {rateNote(id)}</em>}<small>{streams.get(id)?.topic}</small></span></label>)}
      </fieldset>}
      {pending && <div className="source-confirm" role="alert">
        <p>This stops {recording.pending!.monitors.length === 1 ? "1 running monitor that uses" : `${recording.pending!.monitors.length} running monitors that use`} these readings. Their settings are kept.</p>
        <div className="ex-collection-actions"><Button size="sm" onClick={recording.confirm}>Stop monitors and save</Button>
          <Button size="sm" variant="ghost" onClick={recording.cancel}>Cancel</Button></div>
      </div>}
      {excluded.length > 0 && !busy && <div className="source-pending"><span>{excluded.length} {excluded.length === 1 ? "reading was" : "readings were"} added after recording started and {excluded.length === 1 ? "isn't" : "aren't"} recorded.</span>
        <Button size="sm" variant="outline" onClick={() => void recording.save(excluded.map(reading_id =>
          ({ scope: { kind: "reading", connection_id: scope.connection_id, reading_id }, operation: "inherit" })))}>Record {excluded.length === 1 ? "it" : "them"} too</Button></div>}
      {exceptions > 0 && scope.kind === "topic" && <p className="ex-muted">{exceptions} {exceptions === 1 ? "override stays" : "overrides stay"} in place.</p>}
      {recording.problem && <p role="alert" className="ex-preview-error">{recording.problem}</p>}
      {recording.canUndo(scope.connection_id) && !busy && <Button variant="ghost" size="sm" onClick={recording.undo}>Undo</Button>}
      <p className="ex-muted">Recording continues while you’re signed out. Turning it off keeps existing history.</p>
    </>}
  </section>;
}
