import { useMemo } from "react";
import { Box, Cpu, Crosshair, Pencil, Radio } from "lucide-react";
import { InlineName } from "./InlineName";
import { PersonalGroupMembership } from "./PersonalGroupControls";
import { SystemLiveReadings } from "./SystemLiveReadings";
import { SystemTopicBrowser } from "./SystemTopicBrowser";
import type { SystemLiveTelemetry } from "./systemLiveTelemetry";
import type { SystemDocument, SystemEntityKind } from "./systemTypes";
import type { SpatialNode, SpatialWorkspace } from "./types";
type Props = {
  node: SpatialNode;
  document: SystemDocument;
  telemetry?: SystemLiveTelemetry;
  color?: string;
  canEdit: boolean;
  saveError: string;
  disabledReason: string;
  onRename: (name: string) => Promise<void>;
  onEdit: (kind: SystemEntityKind, id: string) => void;
  onSelect: (id: string) => void;
  onFocus: () => void;
  workspace?: SpatialWorkspace;
  onLayout?: (workspace: SpatialWorkspace) => void;
};
function Detail({
  label,
  value,
}: {
  label: string;
  value: string | number | undefined;
}) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value ?? "Not specified"}</dd>
    </>
  );
}
export function SystemObjectInspector({
  node,
  document,
  telemetry,
  color,
  canEdit,
  saveError,
  disabledReason,
  onRename,
  onEdit,
  onSelect,
  onFocus,
  workspace,
  onLayout,
}: Props) {
  const kind = node.system!.kind;
  const connection = document.connections.find(
    (entry) =>
      entry.id ===
      (kind === "connection" ? node.id : node.system?.connectionId),
  );
  const device = document.devices.find((entry) => entry.id === node.id);
  const stream = document.streams.find((entry) => entry.id === node.id);
  const related = useMemo(
    () =>
      document.streams.filter((item) =>
        kind === "connection"
          ? item.connection_id === node.id
          : kind === "device"
            ? item.device_id === node.id
            : stream?.device_id
              ? item.device_id === stream.device_id
              : item.connection_id === stream?.connection_id,
      ),
    [document.streams, kind, node.id, stream],
  );
  const relatedTopics = useMemo(
    () =>
      new Set(
        related.map((item) => JSON.stringify([item.connection_id, item.topic])),
      ).size,
    [related],
  );
  const icon =
    kind === "connection" ? (
      <Box size={23} />
    ) : kind === "device" ? (
      <Cpu size={23} />
    ) : (
      <Radio size={23} />
    );
  return (
    <div className="sp-inspector-content">
      <div className="sp-inspector-identity">
        <div className="sp-object-icon">{icon}</div>
        <div>
          <span className="sp-overline">{kind}</span>
          <h2>
            <InlineName
              value={node.label}
              onSave={onRename}
              editable={canEdit}
              disabledReason={disabledReason}
              saveError={saveError}
              ariaLabel={`Rename ${kind}`}
            />
          </h2>
        </div>
      </div>
      <div className="sp-inspector-actions">
        <button onClick={onFocus}>
          <Crosshair size={13} />
          Focus
        </button>
      </div>
      {telemetry ? (
        <SystemLiveReadings node={node} telemetry={telemetry} color={color} />
      ) : (
        <div className="sp-system-state">
          <i />
          Configured<span>No live connection</span>
        </div>
      )}
      {workspace && onLayout && (
        <PersonalGroupMembership
          nodeId={node.id}
          workspace={workspace}
          onChange={onLayout}
        />
      )}
      {!!related.length && (
        <SystemTopicBrowser
          streams={related}
          selectedStreamId={kind === "stream" ? node.id : undefined}
          telemetry={telemetry}
          onSelect={onSelect}
        />
      )}
      <section className="sp-catalog-details">
        <h3>Definition</h3>
        <dl>
          {kind === "connection" && (
            <>
              <Detail label="Protocol" value="MQTT" />
              <Detail label="Topics" value={relatedTopics} />
              <Detail label="Readings" value={related.length} />
              <Detail label="Host" value={connection?.host} />
              <Detail label="Port" value={connection?.port} />
              <Detail
                label="Transport"
                value={
                  connection?.transport === "websocket" ? "WebSocket" : "TCP"
                }
              />
              <Detail label="TLS" value={connection?.tls ? "Enabled" : "Off"} />
              <Detail
                label="Credential reference"
                value={connection?.credential_ref}
              />
            </>
          )}
          {device && (
            <>
              <Detail label="Kind" value={device.kind} />
              <Detail label="Topics" value={relatedTopics} />
              <Detail label="Readings" value={related.length} />
              <Detail
                label="Parent"
                value={
                  document.devices.find((item) => item.id === device.parent_id)
                    ?.label
                }
              />
            </>
          )}
          {stream && (
            <>
              <Detail label="Value type" value={stream.value_type} />
              <Detail label="Unit" value={stream.unit} />
              <Detail label="Category" value={stream.category} />
              <Detail
                label="Policy"
                value={(stream.policy ?? document.default_policy).mode}
              />
            </>
          )}
        </dl>
        {stream && (
          <>
            <div className="sp-system-binding">
              <span>MQTT topic</span>
              <code>{stream.topic}</code>
            </div>
            {stream.payload_pointer && (
              <div className="sp-system-binding">
                <span>Payload field</span>
                <code>{stream.payload_pointer}</code>
              </div>
            )}
          </>
        )}
        {kind !== "connection" && connection && (
          <button
            className="sp-catalog-related"
            onClick={() => onSelect(connection.id)}
          >
            Connection · {connection.label}
          </button>
        )}
        {stream?.device_id && (
          <button
            className="sp-catalog-related"
            onClick={() => onSelect(stream.device_id!)}
          >
            Device ·{" "}
            {
              document.devices.find((item) => item.id === stream.device_id)
                ?.label
            }
          </button>
        )}
        <button
          className="sp-wide-button sp-system-edit-definition"
          disabled={!canEdit}
          onClick={() => onEdit(kind, node.id)}
        >
          <Pencil size={14} />
          Edit definition
        </button>
      </section>
      <details className="sp-system-identities">
        <summary>Stable identity</summary>
        <code>{node.id}</code>
      </details>
    </div>
  );
}
