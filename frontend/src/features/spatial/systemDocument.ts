import type { CollectionPolicy } from "@/types/collection";
import type {
  SystemConnection,
  SystemDevice,
  SystemDocument,
  SystemEntityKind,
  SystemGroup,
  SystemStream,
} from "./systemTypes";

export const MAX_SYSTEM_BYTES = 1_048_576;
const INVALID_IDS = new Set(["__proto__", "constructor", "prototype"]);
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const hasControl = (value: string) =>
  Array.from(value).some((character) => {
    const code = character.charCodeAt(0);
    return code < 32 || code === 127;
  });

export class SystemValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SystemValidationError";
  }
}

function fail(path: string, message: string): never {
  throw new SystemValidationError(`${path}: ${message}`);
}

function object(value: unknown, path: string, fields: string[]) {
  if (!record(value)) fail(path, "expected an object");
  for (const field of Object.keys(value)) {
    if (!fields.includes(field)) fail(`${path}.${field}`, "unsupported field");
  }
  return value;
}

function text(value: unknown, path: string, max: number, empty = false) {
  if (
    typeof value !== "string" ||
    (!empty && !value.trim()) ||
    value.length > max ||
    hasControl(value)
  )
    fail(
      path,
      `use ${empty ? "0" : "1"}–${max} characters without control characters`,
    );
  return value;
}

function id(value: unknown, path: string, max = 280) {
  const result = text(value, path, max);
  if (!/^[\w:./-]+$/.test(result) || INVALID_IDS.has(result))
    fail(
      path,
      "use letters, numbers, underscores, colons, dots, slashes or hyphens",
    );
  return result;
}

function optionalId(value: unknown, path: string) {
  return value === undefined || value === null ? undefined : id(value, path);
}

function list(value: unknown, path: string, max: number): unknown[] {
  if (!Array.isArray(value) || value.length > max)
    fail(path, `expected a list of at most ${max} entries`);
  return value;
}

function policy(value: unknown, path: string): CollectionPolicy {
  const item = object(value, path, ["mode", "interval_seconds"]);
  if (!["off", "original", "sample"].includes(String(item.mode)))
    fail(`${path}.mode`, "use off, original or sample");
  const interval = item.interval_seconds ?? 10;
  if (
    typeof interval !== "number" ||
    !Number.isInteger(interval) ||
    interval < 1 ||
    interval > 3600
  )
    fail(`${path}.interval_seconds`, "use a whole number between 1 and 3600");
  return {
    mode: item.mode as CollectionPolicy["mode"],
    interval_seconds: interval,
  };
}

function connection(value: unknown, index: number): SystemConnection {
  const path = `connections[${index}]`;
  const item = object(value, path, [
    "id",
    "label",
    "protocol",
    "host",
    "port",
    "transport",
    "tls",
    "websocket_path",
    "credential_ref",
  ]);
  if ((item.protocol ?? "mqtt") !== "mqtt")
    fail(`${path}.protocol`, "only mqtt is currently supported");
  const transport = item.transport ?? "tcp";
  if (transport !== "tcp" && transport !== "websocket")
    fail(`${path}.transport`, "use tcp or websocket");
  const port = item.port ?? 1883;
  if (
    typeof port !== "number" ||
    !Number.isInteger(port) ||
    port < 1 ||
    port > 65535
  )
    fail(`${path}.port`, "use a whole number between 1 and 65535");
  const tls = item.tls ?? false;
  if (typeof tls !== "boolean") fail(`${path}.tls`, "expected true or false");
  const host = text(item.host, `${path}.host`, 253)
    .toLowerCase()
    .replace(/\.$/, "");
  const hostname =
    /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$/;
  const ipv6 =
    /^[0-9a-f:]+$/.test(host) && (host.match(/:/g)?.length ?? 0) >= 2;
  if (!hostname.test(host) && !ipv6)
    fail(
      `${path}.host`,
      "use a hostname or IP address without a URL, credentials or path",
    );
  const websocketPath =
    item.websocket_path === undefined || item.websocket_path === null
      ? undefined
      : text(item.websocket_path, `${path}.websocket_path`, 512);
  if (
    websocketPath !== undefined &&
    (!websocketPath.startsWith("/") || /[\s#]/.test(websocketPath))
  )
    fail(
      `${path}.websocket_path`,
      "use an absolute path without spaces or a fragment",
    );
  if (websocketPath && transport !== "websocket")
    fail(
      `${path}.websocket_path`,
      "only websocket connections have a websocket path",
    );
  return {
    id: id(item.id, `${path}.id`),
    label: text(item.label, `${path}.label`, 120).trim(),
    protocol: "mqtt",
    host,
    port,
    transport,
    tls,
    ...(websocketPath === undefined ? {} : { websocket_path: websocketPath }),
    ...(item.credential_ref === undefined || item.credential_ref === null
      ? {}
      : {
          credential_ref: id(
            item.credential_ref,
            `${path}.credential_ref`,
            160,
          ),
        }),
  };
}

function device(value: unknown, index: number): SystemDevice {
  const path = `devices[${index}]`;
  const item = object(value, path, [
    "id",
    "label",
    "connection_id",
    "parent_id",
    "kind",
  ]);
  const connectionId = optionalId(item.connection_id, `${path}.connection_id`);
  const parentId = optionalId(item.parent_id, `${path}.parent_id`);
  return {
    id: id(item.id, `${path}.id`),
    label: text(item.label, `${path}.label`, 120).trim(),
    kind: text(item.kind ?? "device", `${path}.kind`, 60).trim(),
    ...(connectionId === undefined ? {} : { connection_id: connectionId }),
    ...(parentId === undefined ? {} : { parent_id: parentId }),
  };
}

function stream(value: unknown, index: number): SystemStream {
  const path = `streams[${index}]`;
  const item = object(value, path, [
    "id",
    "label",
    "connection_id",
    "device_id",
    "topic",
    "payload_pointer",
    "value_type",
    "unit",
    "category",
    "policy",
  ]);
  const topic = text(item.topic, `${path}.topic`, 512);
  if (new TextEncoder().encode(topic).length > 512)
    fail(`${path}.topic`, "topic must fit in 512 UTF-8 bytes");
  if (/[+#]/.test(topic))
    fail(`${path}.topic`, "use a concrete MQTT topic without wildcards");
  const valueType = item.value_type ?? "number";
  if (!["number", "boolean", "text", "identifier"].includes(String(valueType)))
    fail(`${path}.value_type`, "use number, boolean, text or identifier");
  const pointer =
    item.payload_pointer === undefined || item.payload_pointer === null
      ? undefined
      : text(item.payload_pointer, `${path}.payload_pointer`, 512, true);
  if (
    pointer !== undefined &&
    pointer !== "" &&
    (!pointer.startsWith("/") || /~(?![01])/.test(pointer))
  )
    fail(
      `${path}.payload_pointer`,
      "use a JSON Pointer such as /temperature, with ~0 and ~1 escapes",
    );
  const deviceId = optionalId(item.device_id, `${path}.device_id`);
  return {
    id: id(item.id, `${path}.id`),
    label: text(item.label, `${path}.label`, 120).trim(),
    connection_id: id(item.connection_id, `${path}.connection_id`),
    topic,
    value_type: valueType as SystemStream["value_type"],
    category: text(item.category ?? "Other", `${path}.category`, 60).trim(),
    ...(deviceId === undefined ? {} : { device_id: deviceId }),
    ...(pointer === undefined ? {} : { payload_pointer: pointer }),
    ...(item.unit === undefined || item.unit === null
      ? {}
      : { unit: text(item.unit, `${path}.unit`, 32, true) }),
    ...(item.policy === undefined || item.policy === null
      ? {}
      : { policy: policy(item.policy, `${path}.policy`) }),
  };
}

function group(value: unknown, index: number): SystemGroup {
  const path = `groups[${index}]`;
  const item = object(value, path, ["id", "label", "color", "member_ids"]);
  if (
    item.color !== undefined &&
    (typeof item.color !== "string" || !/^#[0-9a-fA-F]{6}$/.test(item.color))
  )
    fail(`${path}.color`, "use a six-digit hexadecimal colour");
  return {
    id: id(item.id, `${path}.id`),
    label: text(item.label, `${path}.label`, 120).trim(),
    member_ids: list(item.member_ids, `${path}.member_ids`, 8192).map(
      (member, memberIndex) => id(member, `${path}.member_ids[${memberIndex}]`),
    ),
    ...(item.color === undefined ? {} : { color: item.color as string }),
  };
}

/** Shared reference validation prevents dangling links and ambiguous identities. */
export function validateSystemDocument(value: unknown): SystemDocument {
  const item = object(value, "system", [
    "format",
    "schema_version",
    "label",
    "default_policy",
    "connections",
    "devices",
    "streams",
    "groups",
  ]);
  if (item.format !== "aberration-system" || item.schema_version !== 1)
    fail("system", "expected aberration-system schema version 1");
  const document: SystemDocument = {
    format: "aberration-system",
    schema_version: 1,
    label: text(item.label, "label", 120).trim(),
    default_policy: policy(item.default_policy, "default_policy"),
    connections: list(item.connections, "connections", 128).map(connection),
    devices: list(item.devices, "devices", 2048).map(device),
    streams: list(item.streams, "streams", 4096).map(stream),
    groups: list(item.groups, "groups", 128).map(group),
  };
  const allIds = new Set<string>();
  for (const entity of [
    ...document.connections,
    ...document.devices,
    ...document.streams,
    ...document.groups,
  ]) {
    if (allIds.has(entity.id)) fail("id", `duplicate identity ${entity.id}`);
    allIds.add(entity.id);
  }
  const connectionIds = new Set(document.connections.map((entry) => entry.id));
  const devices = new Map(document.devices.map((entry) => [entry.id, entry]));
  for (const entry of document.devices) {
    if (entry.connection_id && !connectionIds.has(entry.connection_id))
      fail(`device ${entry.id}`, "connection does not exist");
    if (entry.parent_id && !devices.has(entry.parent_id))
      fail(`device ${entry.id}`, "parent device does not exist");
  }
  const completed = new Set<string>();
  for (const entry of document.devices) {
    const chain = new Set<string>();
    let current: SystemDevice | undefined = entry;
    while (current && !completed.has(current.id)) {
      if (chain.has(current.id))
        fail(
          `device ${entry.id}`,
          "parent relationships must not form a cycle",
        );
      chain.add(current.id);
      current = current.parent_id ? devices.get(current.parent_id) : undefined;
    }
    chain.forEach((entryId) => completed.add(entryId));
  }
  for (const entry of document.streams) {
    if (!connectionIds.has(entry.connection_id))
      fail(`stream ${entry.id}`, "connection does not exist");
    if (entry.device_id && !devices.has(entry.device_id))
      fail(`stream ${entry.id}`, "device does not exist");
  }
  const memberIds = new Set(
    [...document.connections, ...document.devices, ...document.streams].map(
      (entry) => entry.id,
    ),
  );
  const assigned = new Set<string>();
  for (const entry of document.groups) {
    if (memberIds.has(`group:${entry.id}`))
      fail(
        `group ${entry.id}`,
        "its rendered group identity collides with an existing object",
      );
    for (const member of entry.member_ids) {
      if (!memberIds.has(member))
        fail(`group ${entry.id}`, `member ${member} does not exist`);
      if (assigned.has(member))
        fail(
          `group ${entry.id}`,
          `member ${member} already belongs to a group`,
        );
      assigned.add(member);
    }
  }
  if (
    new TextEncoder().encode(JSON.stringify(document)).length > MAX_SYSTEM_BYTES
  )
    fail("system", "configuration exceeds 1 MiB");
  return document;
}

function parseJson(contents: string): unknown {
  if (new TextEncoder().encode(contents).length > MAX_SYSTEM_BYTES)
    fail("system", "configuration exceeds 1 MiB");
  try {
    return JSON.parse(contents);
  } catch {
    return fail("system", "invalid JSON");
  }
}

export function parseSystemDocument(contents: string): SystemDocument {
  return validateSystemDocument(parseJson(contents));
}

export function serializeSystemDocument(document: SystemDocument): string {
  const valid = validateSystemDocument(document);
  const pretty = JSON.stringify(valid, null, 2);
  return new TextEncoder().encode(pretty).length <= MAX_SYSTEM_BYTES
    ? pretty
    : JSON.stringify(valid);
}

export function createEmptySystem(label = "My system"): SystemDocument {
  return {
    format: "aberration-system",
    schema_version: 1,
    label,
    default_policy: { mode: "off", interval_seconds: 10 },
    connections: [],
    devices: [],
    streams: [],
    groups: [],
  };
}

function legacyStreamId(chargerId: string, key: string): string {
  const prefix = `ambibox:sensor:${chargerId}:`;
  if (/^[\w.-]+$/.test(key) && prefix.length + key.length <= 128)
    return prefix + key;
  const value = JSON.stringify([chargerId, key]);
  let first = 0x811c9dc5;
  let second = 0x9e3779b9;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    first = Math.imul(first ^ code, 0x01000193);
    second = Math.imul(second ^ code, 0x85ebca6b);
    second ^= second >>> 13;
  }
  return `${prefix}key-${(first >>> 0).toString(16).padStart(8, "0")}${(second >>> 0).toString(16).padStart(8, "0")}`;
}

/** Provider knowledge is isolated here; the saved document has no provider field. */
export function importAmbiboxSystem(value: unknown): SystemDocument {
  if (
    !record(value) ||
    value.schema_version !== 1 ||
    value.provider !== "ambibox"
  )
    fail("catalog", "expected an AmbiBox schema version 1 catalog");
  const document = createEmptySystem("Imported system");
  document.default_policy = policy(value.default_policy, "default_policy");
  for (const [sourceIndex, sourceValue] of list(
    value.sources,
    "sources",
    128,
  ).entries()) {
    if (!record(sourceValue))
      fail(`sources[${sourceIndex}]`, "expected an object");
    const sourceId = id(sourceValue.id, `sources[${sourceIndex}].id`, 120);
    const connectionId = `ambibox:broker:${sourceId}`;
    document.connections.push({
      id: connectionId,
      label: text(sourceValue.label, "source label", 120),
      protocol: "mqtt",
      host: text(sourceValue.host, "source host", 253),
      port: (sourceValue.port ?? 1883) as number,
      transport: "tcp",
      tls: false,
    });
    for (const chargerValue of list(sourceValue.chargers, "chargers", 128)) {
      if (!record(chargerValue)) fail("charger", "expected an object");
      const chargerId = id(chargerValue.id, "charger id", 120);
      const deviceId = `ambibox:charger:${chargerId}`;
      const groupId = `ambibox:group:${chargerId}`;
      document.devices.push({
        id: deviceId,
        label: text(chargerValue.label, "charger label", 120),
        connection_id: connectionId,
        kind: "device",
      });
      const members = [deviceId, connectionId];
      for (const sensorValue of list(chargerValue.sensors, "sensors", 4096)) {
        if (!record(sensorValue)) fail("sensor", "expected an object");
        const streamId = legacyStreamId(
          chargerId,
          text(sensorValue.key, "sensor key", 160),
        );
        const effectivePolicy = sensorValue.policy ?? chargerValue.policy;
        document.streams.push({
          id: streamId,
          label: text(sensorValue.label, "sensor label", 120),
          connection_id: connectionId,
          device_id: deviceId,
          topic: text(sensorValue.upstream_topic, "sensor topic", 512),
          value_type: sensorValue.value_type as SystemStream["value_type"],
          category: text(
            sensorValue.category ?? "Other",
            "sensor category",
            60,
          ),
          ...(sensorValue.unit === null || sensorValue.unit === undefined
            ? {}
            : { unit: text(sensorValue.unit, "sensor unit", 32, true) }),
          ...(effectivePolicy === null || effectivePolicy === undefined
            ? {}
            : { policy: policy(effectivePolicy, "sensor policy") }),
        });
        members.push(streamId);
      }
      // A broker can serve many devices: assign it to its first group only.
      if (
        document.groups.some((entry) => entry.member_ids.includes(connectionId))
      )
        members.splice(1, 1);
      document.groups.push({
        id: groupId,
        label: text(chargerValue.label, "group label", 120),
        color: "#0e8174",
        member_ids: members,
      });
    }
  }
  return validateSystemDocument(document);
}

export function importSystemDocument(contents: string): SystemDocument {
  const value = parseJson(contents);
  return record(value) && value.provider === "ambibox"
    ? importAmbiboxSystem(value)
    : validateSystemDocument(value);
}

const collectionByKind = {
  connection: "connections",
  device: "devices",
  stream: "streams",
  group: "groups",
} as const;

export function renameSystemEntity(
  document: SystemDocument,
  kind: SystemEntityKind,
  entityId: string,
  label: string,
): SystemDocument {
  const key = collectionByKind[kind];
  if (!document[key].some((entry) => entry.id === entityId))
    fail(kind, "object no longer exists");
  return validateSystemDocument({
    ...document,
    [key]: document[key].map((entry) =>
      entry.id === entityId ? { ...entry, label } : entry,
    ),
  });
}

export function systemRemovalIds(
  document: SystemDocument,
  kind: SystemEntityKind,
  entityId: string,
): string[] {
  const removal = new Set([entityId]);
  if (kind === "connection") {
    document.devices
      .filter((entry) => entry.connection_id === entityId)
      .forEach((entry) => removal.add(entry.id));
    document.streams
      .filter((entry) => entry.connection_id === entityId)
      .forEach((entry) => removal.add(entry.id));
  }
  if (kind === "device" || kind === "connection") {
    let changed = true;
    while (changed) {
      changed = false;
      for (const entry of document.devices) {
        if (
          entry.parent_id &&
          removal.has(entry.parent_id) &&
          !removal.has(entry.id)
        ) {
          removal.add(entry.id);
          changed = true;
        }
      }
    }
    document.streams
      .filter((entry) => entry.device_id && removal.has(entry.device_id))
      .forEach((entry) => removal.add(entry.id));
  }
  return [...removal];
}

/** Default removal refuses dependants; the editor can explicitly confirm cascade. */
export function removeSystemEntity(
  document: SystemDocument,
  kind: SystemEntityKind,
  entityId: string,
  cascade = false,
): SystemDocument {
  if (!document[collectionByKind[kind]].some((entry) => entry.id === entityId))
    fail(kind, "object no longer exists");
  const ids = systemRemovalIds(document, kind, entityId);
  if (!cascade && ids.length > 1)
    fail(
      kind,
      `removing this object also removes ${ids.length - 1} dependent objects`,
    );
  const removed = new Set(ids);
  return validateSystemDocument({
    ...document,
    connections: document.connections.filter((entry) => !removed.has(entry.id)),
    devices: document.devices.filter((entry) => !removed.has(entry.id)),
    streams: document.streams.filter((entry) => !removed.has(entry.id)),
    groups: document.groups
      .filter((entry) => !removed.has(entry.id))
      .map((entry) => ({
        ...entry,
        member_ids: entry.member_ids.filter((member) => !removed.has(member)),
      })),
  });
}
