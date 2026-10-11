import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { apiUtils } from "@/lib/api-client";
import type { CollectionPolicy } from "@/types/collection";
import type { SystemCollectionChange, SystemCollectionPreview, SystemRuntime } from "../spatial/systemTypes";

type Props = {
  streamIds: string[];
  runtime?: SystemRuntime;
  revision: number;
  canEdit: boolean;
  saving: boolean;
  onApply: (change: SystemCollectionChange) => Promise<boolean>;
  onRefresh: () => Promise<unknown>;
  canMonitor?: boolean;
  onStatus?: (value: { revision: number; runtime: SystemRuntime }) => void;
};

type EditorProps = Pick<Props, "streamIds" | "revision" | "saving" | "onApply"> & {
  collectionRevision: number;
  initialPolicy?: CollectionPolicy;
};

function CollectionEditor({ streamIds, revision, collectionRevision, initialPolicy, saving, onApply }: EditorProps) {
  const [mode, setMode] = useState<CollectionPolicy["mode"]>(initialPolicy?.mode ?? "sample");
  const [interval, setIntervalSeconds] = useState(initialPolicy?.interval_seconds ?? 10);
  const [reviewed, setReviewed] = useState<{ preview: SystemCollectionPreview; change: SystemCollectionChange }>();
  const [reviewing, setReviewing] = useState(false);
  const [pause, setPause] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const review = async () => {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    const change: SystemCollectionChange = {
      expected_revision: revision, expected_collection_revision: collectionRevision,
      stream_ids: [...streamIds], policy: { mode, interval_seconds: interval },
    };
    setReviewing(true); setReviewed(undefined); setError("");
    try {
      const preview = await apiUtils.post<SystemCollectionPreview>("/v1/system/collection/preview", change,
        { signal: request.signal, redirectOnUnauthorized: false });
      if (!request.signal.aborted) { setReviewed({ preview, change }); setPause(false); }
    } catch (problem) {
      if (!request.signal.aborted) setError(problem instanceof Error ? problem.message : "Collection could not be reviewed.");
    } finally { if (!request.signal.aborted) setReviewing(false); }
  };
  const apply = async () => {
    if (reviewed && await onApply({ ...reviewed.change, pause_affected_monitors: pause })) setReviewed(undefined);
  };
  const update = () => { setReviewed(undefined); setError(""); };
  return <>
    <div className="ex-collection-controls">
      <label><span>Record</span><select aria-label="Collection mode" value={mode} disabled={saving || reviewing}
        onChange={(event) => { update(); setMode(event.target.value as CollectionPolicy["mode"]); }}>
        <option value="off">Off</option><option value="sample">Sample</option><option value="original">Original rate</option>
      </select></label>
      {mode === "sample" && <label><span>Every · seconds</span><input aria-label="Collection interval" type="number" min={1} max={3600} step={1}
        value={interval} disabled={saving || reviewing} onChange={(event) => { update(); setIntervalSeconds(Number(event.target.value)); }} /></label>}
    </div>
    <div className="ex-collection-actions">
      <Button variant="outline" disabled={saving || reviewing || !streamIds.length || !Number.isInteger(interval) || interval < 1 || interval > 3600}
        onClick={() => void review()}>{reviewing ? "Reviewing…" : "Review change"}</Button>
    </div>
    {reviewed && <div className="ex-collection-review">
      <p>{reviewed.change.stream_ids.length.toLocaleString()} {reviewed.change.stream_ids.length === 1 ? "reading" : "readings"} · {mode === "off" ? "Turn collection off"
        : mode === "sample" ? `Sample every ${interval} seconds` : "Record at original rate"}</p>
      {reviewed.preview.sampled_rows_per_day_ceiling > 0 && <p className="ex-muted">Up to {reviewed.preview.sampled_rows_per_day_ceiling.toLocaleString()} numeric samples per day across the catalogue.</p>}
      {reviewed.preview.affected_monitors.length > 0 && <label className="ex-collection-pause"><input type="checkbox" checked={pause}
        onChange={(event) => setPause(event.target.checked)} disabled={saving} />Pause {reviewed.preview.affected_monitors.length} affected {reviewed.preview.affected_monitors.length === 1 ? "monitor" : "monitors"}</label>}
      <div><Button disabled={saving || (reviewed.preview.affected_monitors.length > 0 && !pause)} onClick={() => void apply()}>{saving ? "Applying…" : "Apply"}</Button>
        <Button variant="ghost" disabled={saving} onClick={() => setReviewed(undefined)}>Cancel</Button></div>
    </div>}
    {error && <p role="alert" className="ex-preview-error">{error}</p>}
  </>;
}

export function ExplorerCollection({ streamIds, runtime: savedRuntime, revision, canEdit, saving, onApply, onRefresh, canMonitor = true, onStatus }: Props) {
  const scope = JSON.stringify([revision, streamIds]);
  const [status, setStatus] = useState<{ scope: string; revision: number; runtime: SystemRuntime }>();
  const runtime = status?.scope === scope && (status.runtime.collection_revision ?? 0) >= (savedRuntime?.collection_revision ?? 0)
    ? status.runtime : savedRuntime;
  const selected = useMemo(() => streamIds.flatMap((id) => runtime?.bindings?.[id] ?? []), [streamIds, runtime?.bindings]);
  const enabled = selected.filter((binding) => binding.policy.mode !== "off").length;
  const uniform = selected.length && selected.every((binding) => binding.policy.mode === selected[0]?.policy.mode
    && binding.policy.interval_seconds === selected[0]?.policy.interval_seconds) ? selected[0]?.policy : undefined;
  const binding = streamIds.length === 1 ? runtime?.bindings?.[streamIds[0]!] : undefined;
  const connections = selected.flatMap((item) => item.connection_id ? runtime?.ingress?.sources?.[item.connection_id] ?? [] : []);
  const unavailable = connections.find((item) => ["error", "blocked"].includes(item.state));
  const connecting = connections.some((item) => ["connecting", "reconnecting", "waiting"].includes(item.state));
  const applied = runtime?.collection?.status === "applied";
  const collectionRevision = runtime?.collection_revision ?? 0;
  const label = !enabled ? "Off" : unavailable ? "Unavailable" : !applied ? "Applying…" : connecting ? "Connecting"
    : uniform?.mode === "sample" ? `Sample · ${uniform.interval_seconds}s`
      : uniform?.mode === "original" ? "Original rate" : `${enabled.toLocaleString()} of ${streamIds.length.toLocaleString()} enabled`;
  useEffect(() => {
    if (!streamIds.length) return;
    const request = new AbortController();
    let pending = false;
    const poll = async () => {
      if (document.hidden || pending || request.signal.aborted) return;
      pending = true;
      try {
        const next = await apiUtils.post<{ revision: number; runtime: SystemRuntime }>("/v1/system/collection/status", { stream_ids: streamIds },
          { signal: request.signal, redirectOnUnauthorized: false });
        if (!request.signal.aborted) {
          if (next.revision !== revision) void onRefresh();
          else { setStatus({ ...next, scope }); onStatus?.(next); }
        }
      } catch { /* Preserve the acknowledged policy during a temporary outage. */ }
      finally { pending = false; }
    };
    const timer = setInterval(() => void poll(), enabled && !applied ? 2000 : 5000);
    return () => { clearInterval(timer); request.abort(); };
  }, [streamIds, scope, revision, applied, enabled, onRefresh, onStatus]);
  return <section className="ex-collection" aria-label="Collection">
    <div className="ex-preview-section-heading"><h3>Collection</h3>
      <span className={enabled ? "ex-collection-enabled" : "ex-muted"}>{label}</span>
    </div>
    {canEdit && <CollectionEditor key={JSON.stringify([scope, collectionRevision])} streamIds={streamIds} revision={revision}
      collectionRevision={collectionRevision} initialPolicy={uniform} saving={saving} onApply={onApply} />}
    {unavailable && <p role="alert" className="ex-preview-error">{unavailable.message || "Collection is waiting for a broker connection."}</p>}
    {binding && canMonitor && binding.policy.mode !== "off" && <Link className="ex-collection-monitor" to={`/?create=monitoring&reading=${encodeURIComponent(streamIds[0]!)}`}>Configure monitoring</Link>}
    {enabled > 0 && <p className="ex-muted ex-collection-note">Collection continues when this view disconnects.</p>}
  </section>;
}
