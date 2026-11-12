import { epochMilliseconds } from "@/lib/timestamps";
import { useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { Check, Copy, Pencil, Star } from "lucide-react";
import { SourceIcon } from "@/components/source-icons/SourceIcon";
import { IconPicker } from "@/components/source-icons/IconPicker";
import type { SourceAppearance } from "@/types/source-appearance";
import { InlineName } from "@/components/InlineName";
import { RelativeTime } from "@/components/RelativeTime";
import type { SystemLiveTelemetry } from "@/domain/system/systemLiveTelemetry";
import type { LiveStatus } from "@/types/system-live";
import type { SystemDocument, SystemEntityKind, SystemRuntime } from "@/types/system";
import { ExplorerHistoryChart } from "./ExplorerHistoryChart";
import { readingHistoryKey, useReadingHistorySnapshot, type ReadingHistoryCache } from "@/domain/readings/readingHistoryCache";
import { navigationTrail, type ExplorerNode, type NavigationIndex } from "@/domain/system/navigationIndex";

type Props = {
  node: ExplorerNode;
  index: NavigationIndex;
  document: SystemDocument;
  telemetry: SystemLiveTelemetry;
  historyCache?: ReadingHistoryCache;
  canEdit: boolean;
  saving: boolean;
  error: string;
  onRename: (kind: SystemEntityKind, id: string, label: string) => Promise<void>;
  onEdit: (kind: SystemEntityKind, id: string) => void;
  onAppearanceChange?: (appearance: SourceAppearance | undefined) => Promise<boolean>;
  collectionControls?: ReactNode;
  runtime?: SystemRuntime;
  connectionStatusOnly?: boolean;
  /** Why the last check of an unrecorded broker could not connect; it stands in for the live view's own error. */
  connectionCheck?: string;
  /** The preview stands in for the page heading. */
  pageTitle?: boolean;
  favourite?: boolean;
  onFavourite?: (id: string) => void;
  /** Keep the definition one click away where the page is about something else, such as monitoring. */
  collapseDefinition?: boolean;
  /** Header actions of the hosting page, before the favourite star. */
  actions?: ReactNode;
};

const phases: Record<LiveStatus["phase"], string> = {
  idle: "Disconnected", connecting: "Connecting", live: "Connected",
  waiting: "Waiting", reconnecting: "Reconnecting", blocked: "Unavailable",
  error: "Unavailable", paused: "Paused",
};
const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 });

function Binding({ label, value }: { label: string; value: string }) {
  const [result, setResult] = useState<"copied" | "failed" | null>(null);
  const copy = async () => {
    setResult(null);
    try {
      await navigator.clipboard.writeText(value);
      setResult("copied");
    } catch {
      setResult("failed");
    }
  };
  return (
    <div className="ex-preview-binding">
      <div>
        <span>{label}</span>
        <code>{value}</code>
      </div>
      <button type="button" aria-label={`Copy ${label.toLowerCase()}`} onClick={() => void copy()}>
        {result === "copied" ? <Check size={15} /> : <Copy size={15} />}
      </button>
      {result && <p role={result === "failed" ? "alert" : "status"}>
        {result === "copied" ? "Copied." : "Could not copy. Select the text to copy it manually."}
      </p>}
    </div>
  );
}

export default function ExplorerPreview({
  node, index, document, telemetry, historyCache, canEdit, saving, error, onRename, onEdit, collectionControls, runtime, connectionStatusOnly = false, connectionCheck, pageTitle = false, favourite, onFavourite,
  collapseDefinition = false, actions, onAppearanceChange,
}: Props) {
  const status = useSyncExternalStore(telemetry.subscribeUpdates, telemetry.getStatus);
  const streamsById = useMemo(() => new Map(document.readings.map((stream) => [stream.id, stream])), [document.readings]);
  const brokersById = useMemo(() => new Map(document.brokers.map((broker) => [broker.id, broker])), [document.brokers]);
  const entitiesById = useMemo(() => new Map(document.devices.map((entity) => [entity.id, entity])), [document.devices]);
  const related = useMemo(() => node.streamIds.flatMap((id) => streamsById.get(id) ?? []), [node.streamIds, streamsById]);
  const broker = node.kind === "connection" ? brokersById.get(node.objectId ?? "") : undefined;
  const entity = node.kind === "device" ? entitiesById.get(node.objectId ?? "") : undefined;
  const entityBrokers = useMemo(() => {
    if (!entity) return [];
    const ids = new Set(related.map((item) => item.broker_id));
    if (entity.broker_id) ids.add(entity.broker_id);
    return [...ids].flatMap((id) => brokersById.get(id)?.label ?? []);
  }, [entity, related, brokersById]);
  const stream = node.entityKind === "stream" && node.objectId
    ? streamsById.get(node.objectId)
    : node.kind === "topic" && related.length === 1 ? related[0] : undefined;
  const readingConnection = stream ? brokersById.get(stream.broker_id) : undefined;
  const savedBinding = stream ? runtime?.bindings?.[stream.id] : undefined;
  const history = useReadingHistorySnapshot(historyCache, readingHistoryKey(readingConnection, stream, savedBinding));
  const lastSample = stream?.value_type === "number" ? history.telemetry[history.telemetry.length - 1] : undefined;
  const snapshotId = node.objectId ?? stream?.id;
  const snapshot = snapshotId ? telemetry.getSnapshot(snapshotId) : undefined;
  const connection = status.connections.find((entry) => entry.broker_id === node.connectionId);
  const liveLabel = status.phase === "idle" ? "Disconnected"
    : ["error", "blocked", "paused"].includes(status.phase) ? phases[status.phase]
    : connection?.state === "connected" ? "Connected"
    : connection?.state === "blocked" || connection?.state === "error" ? "Unavailable"
    : connection?.state === "stopped" ? "Disconnected"
    : connection?.state ? connection.state[0]!.toUpperCase() + connection.state.slice(1)
    : phases[status.phase];
  const topicCount = useMemo(() => new Set(related.map((item) => JSON.stringify([item.broker_id, item.topic]))).size, [related]);
  const isReading = node.entityKind === "stream";
  const polled = brokersById.get(node.connectionId ?? "")?.protocol === "http";
  // The whole system and an entity can hold readings of both kinds of source.
  const addresses = polled ? "Request paths"
    : related.some(item => brokersById.get(item.broker_id)?.protocol === "http") ? "Topics and paths" : "MQTT topics";
  const ancestry = navigationTrail(index, node.key);
  const parent = isReading ? ancestry.slice().reverse().find(ancestor => ancestor.kind === "device" || ancestor.kind === "connection") : undefined;
  const trail = <nav className="ex-preview-trail" aria-label="Catalogue ancestry">
    {ancestry.map((ancestor, position) => <span key={ancestor.key}>
      {position > 0 && <span aria-hidden="true"> / </span>}{ancestor.label}
    </span>)}
  </nav>;
  const title = isReading ? stream?.label ?? node.label : node.label;
  const kind = isReading ? "Reading" : node.kind === "connection" ? "Broker"
    : node.kind === "device" ? "Entity" : node.kind === "topic" ? polled ? "Request path" : "Topic path" : "System";
  const iconKind = node.entityKind ?? node.kind;
  const Title = pageTitle ? "h1" : "h2";
  const editable = canEdit && !saving && !!node.entityKind && !!node.objectId;
  const recorded = stream ? runtime?.latest_readings?.[stream.id] : undefined;
  const useRecorded = recorded && (!snapshot?.receivedAt || epochMilliseconds(recorded.received_at) > snapshot.receivedAt);
  const received = useRecorded ? epochMilliseconds(recorded.received_at) : snapshot?.receivedAt;
  const sampleTime = lastSample ? epochMilliseconds(lastSample.timestamp) : undefined;
  const useStoredSample = sampleTime !== undefined && Number.isFinite(sampleTime) && (received == null || sampleTime > received);
  const latest = useStoredSample ? lastSample!.value : useRecorded ? recorded.value : snapshot?.latestValue;
  const receivedAt = useStoredSample ? sampleTime : received;
  const recording = related.length > 0 && related.every(reading => {
    const policy = runtime?.bindings?.[reading.id]?.policy;
    return policy && policy.mode !== "off";
  });
  const sourceIds = new Set(related.flatMap(reading => runtime?.bindings?.[reading.id]?.broker_id ?? []));
  const sources = [...sourceIds].flatMap(id => runtime?.ingress?.sources?.[id] ?? []);
  const recordProblem = sources.find(source => ["error", "blocked"].includes(source.state));
  const recordConnected = sources.length === sourceIds.size && sources.length > 0 && sources.every(source => source.state === "connected");
  const persistentConnection = runtime?.ingress?.sources?.[node.connectionId ?? ""];
  const brokerLabel = persistentConnection?.state === "connected" ? "Connected"
    : persistentConnection?.state === "error" || persistentConnection?.state === "blocked" ? "Unavailable"
      : persistentConnection?.state ? persistentConnection.state[0]!.toUpperCase() + persistentConnection.state.slice(1)
        : connectionCheck && connection?.state !== "connected" ? "Unreachable" : liveLabel;
  const label = connectionStatusOnly ? brokerLabel : recording ? recordProblem || runtime?.collection?.status === "disabled" ? "Unavailable"
    : runtime?.collection?.status !== "applied" ? "Applying…"
      : recordConnected ? "Recording" : sources.some(source => source.state === "reconnecting") ? "Reconnecting" : "Waiting"
    : isReading && status.phase === "idle" && savedBinding?.policy.mode === "off" ? "Recording off" : liveLabel;
  const active = connectionStatusOnly ? label === "Connected" : recording ? label === "Recording" : connection?.state === "connected";
  const tone = active ? "positive" : label === "Unavailable" || label === "Unreachable" ? "danger" : label === "Reconnecting" ? "warning" : "neutral";
  const showStatusDetail = connectionStatusOnly || !isReading || (!recording && status.phase !== "idle");
  const statusDetail = connectionStatusOnly ? "Broker connection"
    : recording ? stream && stream.value_type !== "number" ? "Recorded state" : "Recorded history"
      : status.phase === "idle" ? "No live connection"
        : ["error", "blocked", "paused"].includes(status.phase) ? "Live connection inactive"
          : status.dataSource === "simulated" ? "Simulated data · memory only" : "Live data · memory only";
  const brokerProblem = !connectionStatusOnly ? undefined : persistentConnection
    ? persistentConnection.state !== "connected" ? persistentConnection.message : undefined
    : label === "Unreachable" ? connectionCheck : undefined;
  const problem = brokerProblem ? brokerProblem : recording ? recordProblem?.message : status.phase === "error" ? status.message
    : connection && ["blocked", "error", "reconnecting"].includes(connection.state)
      ? connection.message : status.phase === "blocked" ? status.message : null;
  const edit = canEdit && node.entityKind && node.objectId && <button type="button" disabled={saving}
    onClick={() => onEdit(node.entityKind!, node.objectId!)}><Pencil size={14} /> Edit structure</button>;
  const details = <>
    {stream && <dl><dt>Value type</dt><dd>{stream.value_type}</dd>
      <dt>Category</dt><dd>{stream.category || "Other"}</dd>
    </dl>}
    {broker && <><dl><dt>Protocol</dt><dd>{broker.protocol === "http" ? "HTTP" : `MQTT · ${broker.transport === "websocket" ? "WebSocket" : "TCP"}`}</dd>
      <dt>TLS</dt><dd>{broker.tls ? "Enabled" : "Disabled"}</dd>
    </dl><Binding label="Endpoint" value={`${broker.host}:${broker.port}`} />
      {broker.websocket_path && <Binding label="WebSocket path" value={broker.websocket_path} />}
      <Binding label="Broker ID" value={broker.id} /></>}
    {entity && <><dl><dt>Kind</dt><dd>{entity.kind}</dd>
      <dt>Brokers</dt><dd>{entityBrokers.join(", ") || "Unassigned"}</dd>
      {entity.parent_id && <><dt>Parent entity</dt><dd>{entitiesById.get(entity.parent_id)?.label ?? entity.parent_id}</dd></>}
    </dl><Binding label="Entity ID" value={entity.id} /></>}
    {(stream?.topic ?? node.topic) !== undefined && <Binding key={stream?.topic ?? node.topic}
      label={polled ? "Request path" : stream || related.length > 0 ? "MQTT topic" : "Topic path"} value={(stream?.topic ?? node.topic)!} />}
    {stream?.payload_pointer && <Binding key={stream.payload_pointer} label="Payload field" value={stream.payload_pointer} />}
    {stream?.timestamp_pointer && <Binding key={stream.timestamp_pointer} label="Source timestamp" value={stream.timestamp_pointer} />}
    {!stream && related.length > 0 && <div className="ex-preview-related">
      <span>Configured readings</span>
      <ul>{related.slice(0, 10).map((item) => <li key={item.id}><span className="source-identity"><SourceIcon kind="stream" appearance={item.appearance} />{item.label}</span><small>{item.unit || item.value_type}</small></li>)}</ul>
      {related.length > 10 && <p className="ex-preview-note">{number.format(related.length - 10)} more readings. Browse them in the explorer.</p>}
    </div>}
  </>;
  return (
    <section className="ex-preview" aria-label={`${kind} preview`}>
      <header className={`ex-preview-header${isReading ? " ex-preview-header--reading" : ""}`}>
        <div className="ex-preview-identity">
          {(canEdit || saving) && onAppearanceChange && (node.objectId || node.kind === "topic")
            ? <IconPicker key={node.key} kind={iconKind} label={title} value={node.appearance} color={node.color}
              badge disabled={saving || !canEdit} onChange={onAppearanceChange} />
            : <span className="ex-preview-icon"><SourceIcon kind={iconKind} appearance={node.appearance} color={node.color} size={22} /></span>}
          <div>{!isReading && <span className="ex-preview-kind">{kind} preview</span>}
            <Title className={`ex-preview-title${pageTitle ? " ex-preview-title--page" : ""}`}>
              {canEdit && node.entityKind && node.objectId ? <InlineName key={node.key} value={title}
                onSave={(name) => onRename(node.entityKind!, node.objectId!, name)}
                editable={editable} disabledReason={saving ? "Saving changes…" : undefined}
                saveError={error} ariaLabel={`Rename ${kind.toLowerCase()}`} /> : title}
            </Title>
          </div>
        </div>
        <div className="mn-detail-actions">{actions}{stream && onFavourite && <button className="mn-favourite ex-icon-button" aria-pressed={!!favourite} aria-label={favourite ? "Remove reading from favourites" : "Add reading to favourites"} onClick={() => onFavourite(stream.id)}><Star size={17} /></button>}</div>
      </header>
      {isReading ? parent && <p className="ex-preview-parent">{parent.label}</p> : trail}
      <div className="ex-preview-status" role="status">
        <strong className={`mn-state mn-state--${tone}`}>{label}</strong>
        {showStatusDetail && <span>{statusDetail}</span>}
      </div>
      {problem && <p className="ex-preview-error" role="alert">{problem}</p>}
      {collectionControls}
      {stream ? <>
        <div className="ex-preview-value">
          <span>Latest value</span>
          <strong>{latest == null ? "—" : typeof latest === "number" ? number.format(latest) : String(latest)}
            {latest != null && stream.unit && <small> {stream.unit}</small>}
          </strong>
          <span>{!useStoredSample && (useRecorded ? recorded.is_snapshot : snapshot?.retained) ? "Retained value"
            : <RelativeTime value={receivedAt} mode="elapsed" fallback="No value received yet" />}</span>
        </div>
        {["number", "boolean"].includes(stream.value_type) && <ExplorerHistoryChart
          key={JSON.stringify([stream.id, stream.topic, stream.payload_pointer, stream.value_type,
            readingConnection?.host, readingConnection?.port, readingConnection?.tls, readingConnection?.transport])}
          stream={stream} connection={readingConnection} snapshot={snapshot} binding={savedBinding} historyCache={historyCache} />}
      </> : <div className="ex-preview-metrics">
        <div><strong>{number.format(related.length)}</strong><span>Readings</span></div>
        <div><strong>{number.format(topicCount)}</strong><span>{addresses}</span></div>
        {snapshot?.isAggregate && <div><strong>{number.format(snapshot.rate)}</strong><span>Arrivals / second</span></div>}
      </div>}
      {collapseDefinition ? <section className="ex-preview-details is-collapsible" aria-label="Source details">
        <details><summary>Source details</summary>{edit && <div className="ex-preview-section-heading">{edit}</div>}{isReading && trail}{details}</details>
      </section> : <section className="ex-preview-details" aria-label="Source details">
        <div className="ex-preview-section-heading"><h3>Source details</h3>{edit}</div>{isReading && trail}{details}
      </section>}
    </section>
  );
}
