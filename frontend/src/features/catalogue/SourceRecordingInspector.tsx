import { Button } from "@/components/ui/button";
import type { CollectionPolicy } from "@/types/collection";
import { useState } from "react";
import { originLabel, policyLabel, scopeKey, type RuleScope } from "./collectionRules";
import type { SystemDocument, SystemRuntime } from "./systemTypes";
import type { useRecordingRules } from "./useRecordingRules";

type Props = { scope: RuleScope; ids: string[]; document: SystemDocument; runtime?: SystemRuntime;
  canEdit: boolean; draft: ReturnType<typeof useRecordingRules> };

export function SourceRecordingInspector({ scope, ids, document, runtime, canEdit, draft }: Props) {
  const rule = draft.ownRule(scope);
  const mode = rule?.policy?.mode ?? "inherit";
  const interval = rule?.policy?.interval_seconds ?? 10;
  const [confirmed, setConfirmed] = useState<string>();
  const selected = ids.flatMap(id => runtime?.bindings?.[id] ?? []);
  const enabled = selected.filter(item => item.policy.mode !== "off").length;
  const uniform = selected.length && selected.every(item => item.policy.mode === selected[0]!.policy.mode
    && item.policy.interval_seconds === selected[0]!.policy.interval_seconds) ? selected[0]!.policy : undefined;
  const excluded = draft.pendingReadingIds(ids);
  const exceptions = (runtime?.collection_rules ?? []).filter(item => item.policy && scopeKey(item.scope) !== scopeKey(scope)
    && item.scope.connection_id === scope.connection_id && (scope.kind === "broker" || scope.kind === "topic"
      && (item.scope.kind === "topic" ? item.scope.topic_prefix === scope.topic_prefix || item.scope.topic_prefix?.startsWith(`${scope.topic_prefix}/`)
        : ids.includes(item.scope.reading_id ?? "")))).length;
  const change = (next: string, seconds = interval, future = rule?.include_future_readings ?? false) => {
    draft.edit(next === "inherit" ? { scope, operation: "inherit" } : { scope, operation: "set",
      policy: { mode: next as CollectionPolicy["mode"], interval_seconds: seconds }, include_future_readings: future });
  };
  const preview = draft.preview;
  const reviewKey = JSON.stringify(preview);
  const pause = confirmed === reviewKey;
  return <section className="source-recording" aria-label="Recording configuration">
    <div className="ex-preview-section-heading"><h3>Recording</h3><span>{enabled} of {ids.length} enabled{selected.length && !uniform ? " · Mixed" : uniform ? ` · ${policyLabel(uniform)}` : ""}</span></div>
    {ids.length === 1 && <p className="ex-muted">{originLabel(runtime, ids[0]!, document)}</p>}
    {exceptions > 0 && <p className="ex-muted">{exceptions} {exceptions === 1 ? "child exception" : "child exceptions"} · kept when this policy changes</p>}
    {enabled > 0 && <p className="source-collection-status">Collection: {runtime?.collection?.status === "applied" && runtime.collection.revision === runtime.collection_revision ? "Applied" : runtime?.collection?.status ?? "Applying…"}</p>}
    {canEdit ? <>
      <div className="ex-collection-controls"><label><span>Recording policy</span><select aria-label="Recording policy" value={mode} disabled={draft.saving}
        onChange={event => change(event.target.value)}><option value="inherit">{scope.kind === "broker" ? "Default setting (Off)" : "Use parent setting"}</option>
        <option value="off">Off</option><option value="sample">Sample</option><option value="original">Original rate</option></select></label>
        {mode === "sample" && <label><span>Every · seconds</span><input aria-label="Recording interval" type="number" min={1} max={3600} value={interval}
          disabled={draft.saving} onChange={event => change(mode, Number(event.target.value))} /></label>}</div>
      {scope.kind !== "reading" && <label className="source-future"><input type="checkbox" checked={rule?.include_future_readings ?? false}
        disabled={draft.saving || mode === "inherit"} onChange={event => change(mode, interval, event.target.checked)} />
        <span>Include readings added later<small>Applies to registered readings added to this scope. Existing child exceptions stay in place.</small></span></label>}
      {excluded.length > 0 && <div className="source-pending"><span>{excluded.length} added {excluded.length === 1 ? "reading needs" : "readings need"} review</span>
        <Button variant="outline" disabled={draft.saving} onClick={() => draft.includeReadings(excluded)}>Include current readings</Button></div>}
      {draft.dirty && <div className="source-apply" aria-live="polite">
        {draft.reviewing ? <p>Reviewing changes…</p> : preview && <>
          <p>{preview.starting_readings ?? 0} start · {preview.stopping_readings ?? 0} stop · {preview.rate_changed_readings ?? 0} change rate</p>
          {preview.sampled_rows_per_day_ceiling > 0 && <p className="ex-muted">Up to {preview.sampled_rows_per_day_ceiling.toLocaleString()} numeric samples per day across the catalogue.</p>}
          {preview.affected_monitors.length > 0 && <label className="source-monitor-confirm"><input type="checkbox" checked={pause} onChange={event => setConfirmed(event.target.checked ? reviewKey : undefined)} />
            Stop {preview.affected_monitors.length} affected {preview.affected_monitors.length === 1 ? "monitor" : "monitors"} before applying. Their settings are retained.</label>}
        </>}
        <div className="ex-collection-actions"><Button disabled={draft.saving || !preview || !!preview.affected_monitors.length && !pause}
          onClick={() => void draft.apply(pause)}>{draft.saving ? "Applying…" : "Apply changes"}</Button>
          <Button variant="ghost" disabled={draft.saving} onClick={draft.discard}>Discard changes</Button></div>
      </div>}
      {draft.canUndo && <Button variant="ghost" onClick={draft.stageUndo}>Undo last recording change</Button>}
      {draft.problem && <p role="alert" className="ex-preview-error">{draft.problem}<Button variant="ghost" onClick={draft.rebase}>Review against current configuration</Button></p>}
    </> : <p className="ex-muted">An administrator can change recording settings.</p>}
    <p className="ex-muted">Recording continues after you leave this page. Turning it Off preserves stored history.</p>
  </section>;
}
