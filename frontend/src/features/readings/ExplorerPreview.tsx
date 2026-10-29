import { useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { Box, Check, Copy, Cpu, Folder, Pencil, Radio, Star } from "lucide-react";
import { InlineName } from "@/components/InlineName";
import type { SystemLiveTelemetry } from "@/domain/system/systemLiveTelemetry";
import type { LiveStatus } from "@/types/system-live";
import type { SystemDocument, SystemEntityKind, SystemRuntime } from "@/types/system";
import { ExplorerHistoryChart } from "./ExplorerHistoryChart";
import { readingHistoryKey, useReadingHistorySnapshot, type ReadingHistoryCache } from "@/domain/readings/readingHistoryCache";
import { navigationTrail, type ExplorerNode, type NavigationIndex } from "@/domain/system/navigationIndex";
import { formatExactDateTime } from "@/lib/format-time";

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
  collapseDefinition = false,
}: Props) {
  const status = useSyncExternalStore(telemetry.subscribeUpdates, telemetry.getStatus);
  const streamsById = useMemo(() => new Map(document.streams.map((stream) => [stream.id, stream])), [document.streams]);
  const brokersById = useMemo(() => new Map(document.connections.map((broker) => [broker.id, broker])), [document.connections]);
  const entitiesById = useMemo(() => new Map(document.devices.map((entity) => [entity.id, entity])), [document.devices]);
  const related = useMemo(() => node.streamIds.flatMap((id) => streamsById.get(id) ?? []), [node.streamIds, streamsById]);
  const broker = node.kind === "connection" ? brokersById.get(node.objectId ?? "") : undefined;
  const entity = node.kind === "device" ? entitiesById.get(node.objectId ?? "") : undefined;
  const entityBrokers = useMemo(() => {
    if (!entity) return [];
    const ids = new Set(related.map((item) => item.connection_id));
    if (entity.connection_id) ids.add(entity.connection_id);
    return [...ids].flatMap((id) => brokersById.get(id)?.label ?? []);
  }, [entity, related, brokersById]);
  const stream = node.entityKind === "stream" && node.objectId
    ? streamsById.get(node.objectId)
    : node.kind === "topic" && related.length === 1 ? related[0] : undefined;
  const readingConnection = stream ? brokersById.get(stream.connection_id) : undefined;
  const savedBinding = stream ? runtime?.bindings?.[stream.id] : undefined;
  const history = useReadingHistorySnapshot(historyCache, readingHistoryKey(readingConnection, stream, savedBinding?.entity_id, savedBinding?.telemetry_key));
  const lastSample = stream?.value_type === "number" ? history.telemetry[history.telemetry.length - 1] : undefined;
  const snapshotId = node.objectId ?? stream?.id;
  const snapshot = snapshotId ? telemetry.getSnapshot(snapshotId) : undefined;
  const connection = status.connections.find((entry) => entry.connection_id === node.connectionId);
  const liveLabel = status.phase === "idle" ? "Disconnected"
    : ["error", "blocked", "paused"].includes(status.phase) ? phases[status.phase]
    : connection?.state === "connected" ? "Connected"
    : connection?.state === "blocked" || connection?.state === "error" ? "Unavailable"
    : connection?.state === "stopped" ? "Disconnected"
    : connection?.state ? connection.state[0]!.toUpperCase() + connection.state.slice(1)
    : phases[status.phase];
  const topicCount = useMemo(() => new Set(related.map((item) => JSON.stringify([item.connection_id, item.topic]))).size, [related]);
  const title = node.entityKind === "stream" ? stream?.label ?? node.label : node.label;
  const kind = node.entityKind === "stream" ? "Reading" : node.kind === "connection" ? "Broker"
    : node.kind === "device" ? "Entity" : node.kind === "topic" ? "Topic path" : "System";
  const icon = node.kind === "connection" ? <Box size={22} /> : node.kind === "device" ? <Cpu size={22} />
    : stream ? <Radio size={22} /> : <Folder size={22} />;
  const Title = pageTitle ? "h1" : "h2";
  const editable = canEdit && !saving && !!node.entityKind && !!node.objectId;
  const recorded = stream ? runtime?.latest_readings?.[stream.id] : undefined;
  const useRecorded = recorded && (!snapshot?.receivedAt || Date.parse(recorded.received_at) > snapshot.receivedAt);
  const received = useRecorded ? Date.parse(recorded.received_at) : snapshot?.receivedAt;
  const sampleTime = lastSample ? Date.parse(lastSample.timestamp) : undefined;
  const useStoredSample = sampleTime !== undefined && Number.isFinite(sampleTime) && (received == null || sampleTime > received);
  const latest = useStoredSample ? lastSample!.value : useRecorded ? recorded.value : snapshot?.latestValue;
  const receivedAt = useStoredSample ? sampleTime : received;
  const recording = related.length > 0 && related.every(reading => {
    const policy = runtime?.bindings?.[reading.id]?.policy;
    return policy && policy.mode !== "off";
  });
  const sourceIds = new Set(related.flatMap(reading => runtime?.bindings?.[reading.id]?.connection_id ?? []));
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
    : liveLabel;
  const active = connectionStatusOnly ? label === "Connected" : recording ? label === "Recording" : connection?.state === "connected";
  const tone = active ? "positive" : label === "Unavailable" || label === "Unreachable" ? "danger" : label === "Reconnecting" ? "warning" : "neutral";
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
    {broker && <><dl><dt>Protocol</dt><dd>MQTT · {broker.transport === "websocket" ? "WebSocket" : "TCP"}</dd>
      <dt>TLS</dt><dd>{broker.tls ? "Enabled" : "Disabled"}</dd>
    </dl><Binding label="Endpoint" value={`${broker.host}:${broker.port}`} />
      {broker.websocket_path && <Binding label="WebSocket path" value={broker.websocket_path} />}
      <Binding label="Broker ID" value={broker.id} /></>}
    {entity && <><dl><dt>Kind</dt><dd>{entity.kind}</dd>
      <dt>Brokers</dt><dd>{entityBrokers.join(", ") || "Unassigned"}</dd>
      {entity.parent_id && <><dt>Parent entity</dt><dd>{entitiesById.get(entity.parent_id)?.label ?? entity.parent_id}</dd></>}
    </dl><Binding label="Entity ID" value={entity.id} /></>}
    {(stream?.topic ?? node.topic) !== undefined && <Binding key={stream?.topic ?? node.topic}
      label={stream || related.length > 0 ? "MQTT topic" : "Topic path"} value={(stream?.topic ?? node.topic)!} />}
    {stream?.payload_pointer && <Binding key={stream.payload_pointer} label="Payload field" value={stream.payload_pointer} />}
    {!stream && related.length > 0 && <div className="ex-preview-related">
      <span>Configured readings</span>
      <ul>{related.slice(0, 10).map((item) => <li key={item.id}>{item.label}<small>{item.unit || item.value_type}</small></li>)}</ul>
      {related.length > 10 && <p className="ex-preview-note">{number.format(related.length - 10)} more readings. Browse them in the explorer.</p>}
    </div>}
  </>;
  return (
    <section className="ex-preview" aria-label={`${kind} preview`}>
      <header className="ex-preview-header">
        <div className="ex-preview-identity">
          <span className="ex-preview-icon">{icon}</span>
          <div><span className="ex-preview-kind">{kind} preview</span>
            <Title className={`ex-preview-title${pageTitle ? " ex-preview-title--page" : ""}`}>
              {canEdit && node.entityKind && node.objectId ? <InlineName key={node.key} value={title}
                onSave={(name) => onRename(node.entityKind!, node.objectId!, name)}
                editable={editable} disabledReason={saving ? "Saving changes…" : undefined}
                saveError={error} ariaLabel={`Rename ${kind.toLowerCase()}`} /> : title}
            </Title>
          </div>
        </div>
        <div className="mn-detail-actions">{stream && onFavourite && <button className="mn-favourite ex-icon-button" aria-pressed={!!favourite} aria-label={favourite ? "Remove reading from favourites" : "Add reading to favourites"} onClick={() => onFavourite(stream.id)}><Star size={17} /></button>}</div>
      </header>
      <nav className="ex-preview-trail" aria-label="Catalogue ancestry">
        {navigationTrail(index, node.key).map((ancestor, position) => <span key={ancestor.key}>
          {position > 0 && <span aria-hidden="true"> / </span>}{ancestor.label}
        </span>)}
      </nav>
      <div className="ex-preview-status" role="status">
        <strong className={`mn-state mn-state--${tone}`}>{label}</strong>
        <span>{connectionStatusOnly ? "Broker connection" : recording ? stream && stream.value_type !== "number" ? "Recorded state" : "Recorded history" : status.phase === "idle" ? "No live connection"
          : ["error", "blocked", "paused"].includes(status.phase) ? "Live connection inactive"
            : status.dataSource === "simulated" ? "Simulated data · memory only"
              : "Live data · memory only"}</span>
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
            : receivedAt ? `${useStoredSample ? "Observed" : "Received"} at ${formatExactDateTime(receivedAt)}` : "No value received yet"}</span>
        </div>
        {["number", "boolean"].includes(stream.value_type) && <ExplorerHistoryChart
          key={JSON.stringify([stream.id, stream.topic, stream.payload_pointer, stream.value_type,
            readingConnection?.host, readingConnection?.port, readingConnection?.tls, readingConnection?.transport])}
          stream={stream} connection={readingConnection} snapshot={snapshot} binding={runtime?.bindings?.[stream.id]} historyCache={historyCache} />}
      </> : <div className="ex-preview-metrics">
        <div><strong>{number.format(related.length)}</strong><span>Readings</span></div>
        <div><strong>{number.format(topicCount)}</strong><span>MQTT topics</span></div>
        {snapshot?.isAggregate && <div><strong>{number.format(snapshot.rate)}</strong><span>Arrivals / second</span></div>}
      </div>}
      {collapseDefinition ? <section className="ex-preview-details is-collapsible" aria-label="Definition">
        <details><summary>Definition</summary>{edit && <div className="ex-preview-section-heading">{edit}</div>}{details}</details>
      </section> : <section className="ex-preview-details" aria-label="Definition">
        <div className="ex-preview-section-heading"><h3>Definition</h3>{edit}</div>{details}
      </section>}
    </section>
  );
}
