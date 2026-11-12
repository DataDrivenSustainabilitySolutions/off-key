import { useMemo, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { IconPicker } from "@/components/source-icons/IconPicker";
import { getErrorMessage } from "@/lib/errors";
import {
  collectionByKind,
  connectionDefaults,
  ENTITY_NOUN,
  httpPort,
  newSystemEntity,
  removeSystemEntity,
  systemRemovalIds,
  upsertSystemEntity,
} from "@/domain/system/systemDocument";
import type {
  SystemConnection,
  SystemDevice,
  SystemDocument,
  SystemEntityKind,
  SystemGroup,
  SystemStream,
} from "@/types/system";

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
function initialEntity(document: SystemDocument, kind: SystemEntityKind, id?: string): Entity {
  const saved = id && (document[collectionByKind[kind]] as Entity[]).find((entity) => entity.id === id);
  return saved ? structuredClone(saved) : newSystemEntity(document, kind);
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
  const isPolled = (connectionId?: string) =>
    baseline.brokers.find((item) => item.id === connectionId)?.protocol === "http";
  // An HTTP API is asked for a request path; an MQTT broker sends topics.
  const polled = kind === "connection" ? connection.protocol === "http" : isPolled(stream.broker_id);
  // Readings hold topics or request paths, which one type cannot take from the other.
  const typeFixed = baseline.readings.some((item) => item.broker_id === entityId);
  // The baseline is fixed for the dialog's lifetime, so typing only reruns
  // the search, not the dependency walk.
  const matches = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return [
      ...baseline.brokers,
      ...baseline.devices,
      ...baseline.readings,
    ].filter((item) => item.label.toLowerCase().includes(needle));
  }, [baseline, search]);
  const dependencies = useMemo(
    () => (entityId ? systemRemovalIds(baseline, kind, entityId) : []),
    [baseline, kind, entityId],
  );
  const existingDevice =
    kind === "device" && entityId
      ? baseline.devices.find((item) => item.id === entityId)
      : undefined;
  const movingStreams = existingDevice
    ? baseline.readings.filter(
        (item) =>
          item.device_id === entityId &&
          item.broker_id === existingDevice.broker_id,
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
      else next = upsertSystemEntity(baseline, kind, entity);
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
          {entityId ? "Edit" : "Add"} {ENTITY_NOUN[kind]}
        </span>
        <h2>{entityId ? entity.label : `A new ${ENTITY_NOUN[kind]}.`}</h2>
        <p className="sp-system-intro">
          Save the definition that describes your connected system.
        </p>
      </div>
      <fieldset disabled={disabled}>
        <div className="source-appearance-field"><span>Appearance<small>A small icon and a quiet color.</small></span>
          <IconPicker kind={kind} label={entity.label} value={entity.appearance} color={kind === "group" ? group.color : undefined}
            disabled={disabled} onChange={appearance => update({ appearance })} />
        </div>
        <label>
          Name
          <input
            aria-label={`${ENTITY_NOUN[kind]} name`}
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
              Type
              <select
                aria-label="Connection type"
                value={connection.protocol}
                disabled={typeFixed}
                onChange={(event) =>
                  update({
                    ...connectionDefaults(
                      event.target.value as SystemConnection["protocol"],
                    ),
                    websocket_path: undefined,
                  })
                }
              >
                <option value="mqtt">MQTT broker</option>
                <option value="http">HTTP API</option>
              </select>
              {typeFixed && (
                <small>The type is fixed while readings use this connection.</small>
              )}
            </label>
            <label>
              {polled ? "Host" : "Broker host"}
              <input
                aria-label={polled ? "Host" : "Broker host"}
                placeholder={polled ? "api.example.com" : "mqtt.example.com"}
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
                  aria-label={polled ? "Port" : "Broker port"}
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
              {polled ? (
                <label>
                  Scheme
                  <select
                    aria-label="Scheme"
                    value={connection.tls ? "https" : "http"}
                    onChange={(event) => {
                      const tls = event.target.value === "https";
                      // The port follows the scheme until one is typed in.
                      const followed = connection.port === httpPort(!tls);
                      update({ tls, ...(followed ? { port: httpPort(tls) } : {}) });
                    }}
                  >
                    <option value="https">HTTPS</option>
                    <option value="http">HTTP</option>
                  </select>
                </label>
              ) : (
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
              )}
            </div>
            {!polled && (
              <label className="sp-system-check">
                <input
                  type="checkbox"
                  checked={connection.tls}
                  onChange={(event) => update({ tls: event.target.checked })}
                />
                Use TLS
              </label>
            )}
            {!polled && connection.transport === "websocket" && (
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
              value={(kind === "stream" ? stream : device).broker_id ?? ""}
              onChange={(event) =>
                update({
                  broker_id: event.target.value || undefined,
                  ...(kind === "stream" ? { device_id: undefined } : {}),
                  ...(kind === "stream" && !isPolled(event.target.value)
                    ? { timestamp_pointer: undefined }
                    : {}),
                })
              }
              required={kind === "stream"}
            >
              <option value="">
                {kind === "stream" ? "Choose a connection" : "No connection"}
              </option>
              {baseline.brokers.map((item) => (
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
                      !item.broker_id ||
                      item.broker_id === stream.broker_id,
                  )
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              {polled ? "Request path" : "MQTT topic"}
              <input
                aria-label={polled ? "Request path" : "MQTT topic"}
                placeholder={
                  polled ? "/v1/stations/7/latest" : "building/room-a/temperature"
                }
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
              <small>
                Leave empty to use the complete {polled ? "reply" : "message value"}.
              </small>
            </label>
            {polled && (
              <label>
                Source timestamp
                <input
                  aria-label="Source timestamp"
                  placeholder="Optional JSON pointer, e.g. /observed_at"
                  maxLength={512}
                  value={stream.timestamp_pointer ?? ""}
                  onChange={(event) =>
                    update({ timestamp_pointer: event.target.value || undefined })
                  }
                />
                <small>
                  Where the reply says when the value was measured. A poll that
                  repeats it is not recorded again.
                </small>
              </label>
            )}
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
              Find members
              <input
                aria-label="Find collection members"
                placeholder="Search connections, devices, streams…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <div className="sp-system-members">
              <p className="sp-system-count">
                {group.member_ids.length} members · selecting an object moves it
                into this collection.
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
                Remove this {ENTITY_NOUN[kind]}
                {dependencies.length > 1
                  ? ` and ${dependencies.length - 1} dependent objects`
                  : ""}{" "}
                from the saved definition? Related collection memberships will also
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
              Remove {ENTITY_NOUN[kind]}
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
