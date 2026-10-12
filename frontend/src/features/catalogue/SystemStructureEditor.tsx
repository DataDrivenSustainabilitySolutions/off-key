import { useRef, useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getErrorMessage } from "@/lib/errors";
import {
  removeSystemEntity,
  systemRemovalIds,
  validateSystemDocument,
} from "./systemDocument";
import type {
  SystemConnection,
  SystemDevice,
  SystemDocument,
  SystemEntityKind,
  SystemGroup,
  SystemStream,
} from "./systemTypes";

type Entity = SystemConnection | SystemDevice | SystemStream | SystemGroup;
type Props = {
  document: SystemDocument;
  kind: SystemEntityKind;
  entityId?: string;
  revision: number;
  canEdit: boolean;
  saving: boolean;
  saveError: string;
  onSave: (document: SystemDocument, revision: number) => Promise<boolean>;
  onDone: () => void;
};
const plural = {
  connection: "connections",
  device: "devices",
  stream: "streams",
  group: "groups",
} as const;
const noun = {
  connection: "connection",
  device: "device",
  stream: "stream",
  group: "group",
};

function initialEntity(
  document: SystemDocument,
  kind: SystemEntityKind,
  id?: string,
): Entity {
  const saved = id && document[plural[kind]].find((entity) => entity.id === id);
  if (saved) return structuredClone(saved);
  const identity = {
    id: `${kind}:${crypto.randomUUID()}`,
    label: `New ${noun[kind]}`,
  };
  switch (kind) {
    case "connection":
      return {
        ...identity,
        protocol: "mqtt",
        host: "",
        port: 1883,
        transport: "tcp",
        tls: false,
      };
    case "device":
      return {
        ...identity,
        kind: "device",
        connection_id: document.connections[0]?.id,
      };
    case "stream":
      return {
        ...identity,
        connection_id: document.connections[0]?.id ?? "",
        topic: "",
        value_type: "number",
        category: "Other",
        policy: { mode: "off", interval_seconds: 10 },
      };
    case "group":
      return { ...identity, color: "#397f74", member_ids: [] };
  }
}

/** A structure edit keeps its original revision until the user reviews a conflict. */
export function SystemStructureEditor({
  document,
  kind,
  entityId,
  revision,
  canEdit,
  saving,
  saveError,
  onSave,
  onDone,
}: Props) {
  const [baseline] = useState(() => structuredClone(document));
  const [baseRevision] = useState(revision);
  const [entity, setEntity] = useState(() =>
    initialEntity(document, kind, entityId),
  );
  const [error, setError] = useState("");
  const [failed, setFailed] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [search, setSearch] = useState("");
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const disabled = !canEdit || saving || pending;
  const update = (fields: Partial<Entity>) => {
    setEntity((current) => ({ ...current, ...fields }));
    setError("");
    setFailed(false);
  };
  const connection = entity as SystemConnection;
  const device = entity as SystemDevice;
  const stream = entity as SystemStream;
  const group = entity as SystemGroup;
  const objects = [
    ...baseline.connections,
    ...baseline.devices,
    ...baseline.streams,
  ];
  const matches = objects.filter((item) =>
    item.label.toLowerCase().includes(search.trim().toLowerCase()),
  );
  const dependencies = entityId
    ? systemRemovalIds(baseline, kind, entityId)
    : [];
  const existingDevice =
    kind === "device" && entityId
      ? baseline.devices.find((item) => item.id === entityId)
      : undefined;
  const movingStreams = existingDevice
    ? baseline.streams.filter(
        (item) =>
          item.device_id === entityId &&
          item.connection_id === existingDevice.connection_id,
      )
    : [];
  const submit = async (remove = false) => {
    if (busy.current || disabled) return;
    setError("");
    setFailed(false);
    busy.current = true;
    setPending(true);
    try {
      let next: SystemDocument;
      if (remove && entityId)
        next = removeSystemEntity(baseline, kind, entityId, true);
      else {
        const key = plural[kind];
        const exists = baseline[key].some((item) => item.id === entity.id);
        const values = exists
          ? baseline[key].map((item) => (item.id === entity.id ? entity : item))
          : [...baseline[key], entity];
        const candidate = { ...baseline, [key]: values };
        if (kind === "group") {
          const members = new Set(group.member_ids);
          candidate.groups = (values as SystemGroup[]).map((item) =>
            item.id === group.id
              ? item
              : {
                  ...item,
                  member_ids: item.member_ids.filter((id) => !members.has(id)),
                },
          );
        }
        if (
          kind === "device" &&
          device.connection_id &&
          device.connection_id !== existingDevice?.connection_id
        ) {
          const movingIds = new Set(movingStreams.map((item) => item.id));
          candidate.streams = baseline.streams.map((item) =>
            movingIds.has(item.id)
              ? { ...item, connection_id: device.connection_id! }
              : item,
          );
        }
        next = validateSystemDocument(candidate);
      }
      if (await onSave(next, baseRevision)) onDone();
      else setFailed(true);
    } catch (failure) {
      setError(getErrorMessage(failure));
    } finally {
      busy.current = false;
      setPending(false);
    }
  };
  return (
    <form
      className="sp-system-editor sp-inspector-content"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="sp-system-editor-heading">
        <span className="sp-overline">
          {entityId ? "Edit" : "Add"} {noun[kind]}
        </span>
        <h2>{entityId ? entity.label : `A new ${noun[kind]}.`}</h2>
        <p className="sp-system-intro">
          Save the definition that describes your connected system.
        </p>
      </div>
      <fieldset disabled={disabled}>
        <label>
          Name
          <input
            aria-label={`${noun[kind]} name`}
            maxLength={120}
            value={entity.label}
            onChange={(event) => update({ label: event.target.value })}
            required
            autoFocus
          />
        </label>
        {kind === "connection" && (
          <>
            <label>
              Broker host
              <input
                aria-label="Broker host"
                placeholder="mqtt.example.com"
                maxLength={253}
                value={connection.host}
                onChange={(event) => update({ host: event.target.value })}
                required
              />
            </label>
            <div className="sp-system-field-pair">
              <label>
                Port
                <input
                  aria-label="Broker port"
                  type="number"
                  min={1}
                  max={65535}
                  value={connection.port}
                  onChange={(event) =>
                    update({ port: Number(event.target.value) })
                  }
                  required
                />
              </label>
              <label>
                Transport
                <select
                  aria-label="Transport"
                  value={connection.transport}
                  onChange={(event) =>
                    update({
                      transport: event.target
                        .value as SystemConnection["transport"],
                      ...(event.target.value === "tcp"
                        ? { websocket_path: undefined }
                        : {}),
                    })
                  }
                >
                  <option value="tcp">MQTT / TCP</option>
                  <option value="websocket">MQTT / WebSocket</option>
                </select>
              </label>
            </div>
            <label className="sp-system-check">
              <input
                type="checkbox"
                checked={connection.tls}
                onChange={(event) => update({ tls: event.target.checked })}
              />
              Use TLS
            </label>
            {connection.transport === "websocket" && (
              <label>
                WebSocket path
                <input
                  aria-label="WebSocket path"
                  placeholder="/mqtt"
                  maxLength={512}
                  value={connection.websocket_path ?? ""}
                  onChange={(event) =>
                    update({ websocket_path: event.target.value || undefined })
                  }
                />
              </label>
            )}
            <label>
              Credential reference
              <input
                aria-label="Credential reference"
                placeholder="Optional saved credential name"
                maxLength={160}
                value={connection.credential_ref ?? ""}
                onChange={(event) =>
                  update({ credential_ref: event.target.value || undefined })
                }
              />
              <small>
                Reference credentials configured for this connection. Passwords
                stay out of exported files.
              </small>
            </label>
          </>
        )}
        {(kind === "device" || kind === "stream") && (
          <label>
            Connection
            <select
              aria-label="Connection"
              value={(kind === "stream" ? stream : device).connection_id ?? ""}
              onChange={(event) =>
                update({
                  connection_id: event.target.value || undefined,
                  ...(kind === "stream" ? { device_id: undefined } : {}),
                })
              }
              required={kind === "stream"}
            >
              <option value="">
                {kind === "stream" ? "Choose a connection" : "No connection"}
              </option>
              {baseline.connections.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
            {kind === "device" && movingStreams.length > 0 && (
              <small>
                Changing the connection moves this device’s{" "}
                {movingStreams.length}{" "}
                {movingStreams.length === 1 ? "stream" : "streams"} to the
                chosen connection. Clearing it keeps existing bindings.
              </small>
            )}
          </label>
        )}
        {kind === "device" && (
          <>
            <label>
              Kind
              <input
                aria-label="Device kind"
                placeholder="e.g. weather-station, machine, room"
                value={device.kind}
                maxLength={60}
                onChange={(event) => update({ kind: event.target.value })}
              />
            </label>
            <label>
              Parent device
              <select
                aria-label="Parent device"
                value={device.parent_id ?? ""}
                onChange={(event) =>
                  update({ parent_id: event.target.value || undefined })
                }
              >
                <option value="">No parent</option>
                {baseline.devices
                  .filter((item) => item.id !== device.id)
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
              </select>
            </label>
          </>
        )}
        {kind === "stream" && (
          <>
            <label>
              Device
              <select
                aria-label="Device"
                value={stream.device_id ?? ""}
                onChange={(event) =>
                  update({ device_id: event.target.value || undefined })
                }
              >
                <option value="">Independent stream</option>
                {baseline.devices
                  .filter(
                    (item) =>
                      !item.connection_id ||
                      item.connection_id === stream.connection_id,
                  )
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              MQTT topic
              <input
                aria-label="MQTT topic"
                placeholder="building/room-a/temperature"
                maxLength={512}
                value={stream.topic}
                onChange={(event) => update({ topic: event.target.value })}
                required
              />
            </label>
            <label>
              Payload field
              <input
                aria-label="Payload field"
                placeholder="Optional JSON pointer, e.g. /temperature"
                maxLength={512}
                value={stream.payload_pointer ?? ""}
                onChange={(event) =>
                  update({ payload_pointer: event.target.value || undefined })
                }
              />
              <small>Leave empty to use the complete message value.</small>
            </label>
            <div className="sp-system-field-pair">
              <label>
                Value type
                <select
                  aria-label="Value type"
                  value={stream.value_type}
                  onChange={(event) =>
                    update({
                      value_type: event.target
                        .value as SystemStream["value_type"],
                    })
                  }
                >
                  <option value="number">Number</option>
                  <option value="boolean">Boolean</option>
                  <option value="text">Text</option>
                  <option value="identifier">Identifier</option>
                </select>
              </label>
              <label>
                Unit
                <input
                  aria-label="Unit"
                  placeholder="Optional"
                  value={stream.unit ?? ""}
                  maxLength={32}
                  onChange={(event) =>
                    update({ unit: event.target.value || undefined })
                  }
                />
              </label>
            </div>
            <label>
              Category
              <input
                aria-label="Category"
                value={stream.category}
                maxLength={60}
                onChange={(event) => update({ category: event.target.value })}
              />
            </label>
          </>
        )}
        {kind === "group" && (
          <>
            <label>
              Colour
              <input
                aria-label="Group colour"
                type="color"
                value={group.color ?? "#397f74"}
                onChange={(event) => update({ color: event.target.value })}
              />
            </label>
            <label>
              Find members
              <input
                aria-label="Find group members"
                placeholder="Search connections, devices, streams…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <div className="sp-system-members">
              <p className="sp-system-count">
                {group.member_ids.length} members · selecting an object moves it
                into this group.
              </p>
              <div className="sp-system-member-picker">
                {matches.slice(0, 60).map((item) => (
                  <label className="sp-system-check" key={item.id}>
                    <input
                      type="checkbox"
                      checked={group.member_ids.includes(item.id)}
                      onChange={(event) =>
                        update({
                          member_ids: event.target.checked
                            ? [...group.member_ids, item.id]
                            : group.member_ids.filter((id) => id !== item.id),
                        })
                      }
                    />
                    <span title={item.label}>{item.label}</span>
                  </label>
                ))}
                {matches.length > 60 && (
                  <small>
                    Search to narrow {matches.length} matching objects.
                  </small>
                )}
              </div>
            </div>
          </>
        )}
      </fieldset>
      {(error || (failed && saveError)) && (
        <p className="sp-inline-name-error" role="alert">
          {error || saveError}
        </p>
      )}
      {failed && !saveError && (
        <p role="alert">
          Changes were not saved. Review the saved version before trying again.
        </p>
      )}
      <div className="sp-system-form-actions">
        <Button type="submit" disabled={disabled}>
          {saving || pending ? "Saving…" : "Save changes"}
        </Button>
        <Button type="button" variant="outline" disabled={saving || pending} onClick={onDone}>
          Cancel
        </Button>
      </div>
      {entityId && (
        <section className="sp-system-remove">
          {removing ? (
            <>
              <p>
                Remove this {noun[kind]}
                {dependencies.length > 1
                  ? ` and ${dependencies.length - 1} dependent objects`
                  : ""}{" "}
                from the saved definition? Related group memberships will also
                be removed.
              </p>
              <Button
                type="button"
                variant="destructive"
                disabled={disabled}
                onClick={() => void submit(true)}
              >
                Confirm removal
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={saving || pending}
                onClick={() => setRemoving(false)}
              >
                Keep it
              </Button>
            </>
          ) : (
            <Button
              type="button"
              variant="destructive"
              disabled={disabled}
              onClick={() => setRemoving(true)}
            >
              Remove {noun[kind]}
            </Button>
          )}
        </section>
      )}
      {!entityId && (
        <span className="sp-system-editor-note">
          <Plus size={12} /> New objects receive a stable identity when saved.
        </span>
      )}
    </form>
  );
}
