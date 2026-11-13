import type { CollectionPolicy } from "@/types/collection";
import { SOURCE_COLORS, type SourceAppearance, type TopicAppearance } from "@/types/source-appearance";
import type {
  SystemConnection,
  SystemDevice,
  SystemDocument,
  SystemEntityKind,
  SystemGroup,
  SystemStream,
} from "@/types/system";

export const MAX_SYSTEM_BYTES = 1_048_576;
const DEFAULT_MQTT_PORT = 1883;
/** The port an HTTP source uses when none is saved. */
export const httpPort = (tls: boolean) => (tls ? 443 : 80);
/** What the editor starts a connection of each type with. */
export const connectionDefaults = (protocol: SystemConnection["protocol"]) =>
  protocol === "http"
    ? { protocol, port: httpPort(true), transport: "tcp" as const, tls: true }
    : { protocol, port: DEFAULT_MQTT_PORT, transport: "tcp" as const, tls: false };
const DEFAULT_POLICY: CollectionPolicy = { mode: "off", interval_seconds: 10 };
export const DEFAULT_GROUP_COLOR = "#397f74";
const INVALID_IDS = new Set(["__proto__", "constructor", "prototype"]);
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
/** C0 controls and DEL, matching the backend; paths also reject the space character. */
const hasControl = (value: string, forbidSpace = false) =>
  Array.from(value).some((character) => {
    const code = character.charCodeAt(0);
    return code < (forbidSpace ? 33 : 32) || code === 127;
  });
/** An IPv6 literal without a zone index, as the URL parser reads it. */
const isIpv6 = (host: string) => {
  if (!host.includes(":")) return false;
  try {
    return new URL(`http://[${host}]/`).hostname !== "";
  } catch {
    return false;
  }
};

class SystemValidationError extends Error {
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
  const interval = item.interval_seconds ?? DEFAULT_POLICY.interval_seconds;
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

function appearance(value: unknown, path: string): { appearance?: SourceAppearance } {
  if (value === undefined || value === null) return {};
  const item = object(value, path, ["icon", "color"]);
  const result: SourceAppearance = {};
  if (item.icon !== undefined && item.icon !== null) {
    const icon = text(item.icon, `${path}.icon`, 40);
    if (!/^[a-z][a-z0-9-]*$/.test(icon)) fail(`${path}.icon`, "use an icon name");
    result.icon = icon;
  }
  if (item.color !== undefined && item.color !== null) {
    if (!SOURCE_COLORS.some(color => color === item.color))
      fail(`${path}.color`, "use a colour from the icon palette");
    result.color = item.color as SourceAppearance["color"];
  }
  return Object.keys(result).length ? { appearance: result } : {};
}

function topicAppearance(value: unknown, index: number): TopicAppearance {
  const path = `topic_appearances[${index}]`;
  const item = object(value, path, ["broker_id", "topic", "appearance"]);
  const topic = text(item.topic, `${path}.topic`, 512, true);
  if (/[+#]/.test(topic) || new TextEncoder().encode(topic).length > 512)
    fail(`${path}.topic`, "use a concrete MQTT path of at most 512 UTF-8 bytes");
  if (!record(item.appearance)) fail(`${path}.appearance`, "expected an object");
  return { broker_id: id(item.broker_id, `${path}.broker_id`), topic,
    appearance: appearance(item.appearance, `${path}.appearance`).appearance ?? {} };
}

function connection(value: unknown, index: number): SystemConnection {
  const path = `brokers[${index}]`;
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
    "appearance",
  ]);
  const protocol = item.protocol ?? "mqtt";
  if (protocol !== "mqtt" && protocol !== "http")
    fail(`${path}.protocol`, "use mqtt or http");
  const transport = item.transport ?? "tcp";
  if (transport !== "tcp" && transport !== "websocket")
    fail(`${path}.transport`, "use tcp or websocket");
  const tls = item.tls ?? false;
  if (typeof tls !== "boolean") fail(`${path}.tls`, "expected true or false");
  const port =
    item.port ?? (protocol === "http" ? httpPort(tls) : DEFAULT_MQTT_PORT);
  if (
    typeof port !== "number" ||
    !Number.isInteger(port) ||
    port < 1 ||
    port > 65535
  )
    fail(`${path}.port`, "use a whole number between 1 and 65535");
  const host = text(item.host, `${path}.host`, 253)
    .toLowerCase()
    .replace(/\.$/, "");
  const hostname =
    /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$/;
  if (!hostname.test(host) && !isIpv6(host))
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
    (!websocketPath.startsWith("/") || hasControl(websocketPath, true) || websocketPath.includes("#"))
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
  if (protocol === "http" && transport !== "tcp")
    fail(`${path}.transport`, "an HTTP source has no MQTT transport");
  return {
    ...appearance(item.appearance, `${path}.appearance`),
    id: id(item.id, `${path}.id`),
    label: text(item.label, `${path}.label`, 120).trim(),
    protocol,
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
    "broker_id",
    "parent_id",
    "kind",
    "appearance",
  ]);
  const connectionId = optionalId(item.broker_id, `${path}.broker_id`);
  const parentId = optionalId(item.parent_id, `${path}.parent_id`);
  return {
    ...appearance(item.appearance, `${path}.appearance`),
    id: id(item.id, `${path}.id`),
    label: text(item.label, `${path}.label`, 120).trim(),
    kind: text(item.kind ?? "device", `${path}.kind`, 60).trim(),
    ...(connectionId === undefined ? {} : { broker_id: connectionId }),
    ...(parentId === undefined ? {} : { parent_id: parentId }),
  };
}

/** An optional RFC 6901 JSON Pointer; the empty pointer is the whole value. */
function pointer(value: unknown, path: string) {
  if (value === undefined || value === null) return undefined;
  const result = text(value, path, 512, true);
  if (result !== "" && (!result.startsWith("/") || /~(?![01])/.test(result)))
    fail(path, "use a JSON Pointer such as /temperature, with ~0 and ~1 escapes");
  return result;
}

function stream(value: unknown, index: number): SystemStream {
  const path = `readings[${index}]`;
  const item = object(value, path, [
    "id",
    "label",
    "broker_id",
    "device_id",
    "topic",
    "payload_pointer",
    "timestamp_pointer",
    "value_type",
    "unit",
    "category",
    "policy",
    "appearance",
  ]);
  const topic = text(item.topic, `${path}.topic`, 512);
  if (new TextEncoder().encode(topic).length > 512)
    fail(`${path}.topic`, "topic must fit in 512 UTF-8 bytes");
  if (/[+#]/.test(topic))
    fail(`${path}.topic`, "use a topic or request path without + or #");
  const valueType = item.value_type ?? "number";
  if (!["number", "boolean", "text", "identifier"].includes(String(valueType)))
    fail(`${path}.value_type`, "use number, boolean, text or identifier");
  const payload = pointer(item.payload_pointer, `${path}.payload_pointer`);
  const timestamp = pointer(item.timestamp_pointer, `${path}.timestamp_pointer`);
  const deviceId = optionalId(item.device_id, `${path}.device_id`);
  return {
    ...appearance(item.appearance, `${path}.appearance`),
    id: id(item.id, `${path}.id`),
    label: text(item.label, `${path}.label`, 120).trim(),
    broker_id: id(item.broker_id, `${path}.broker_id`),
    topic,
    value_type: valueType as SystemStream["value_type"],
    category: text(item.category ?? "Other", `${path}.category`, 60).trim(),
    ...(deviceId === undefined ? {} : { device_id: deviceId }),
    ...(payload === undefined ? {} : { payload_pointer: payload }),
    ...(timestamp === undefined ? {} : { timestamp_pointer: timestamp }),
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
  const item = object(value, path, ["id", "label", "color", "member_ids", "appearance"]);
  if (
    item.color !== undefined &&
    (typeof item.color !== "string" || !/^#[0-9a-fA-F]{6}$/.test(item.color))
  )
    fail(`${path}.color`, "use a six-digit hexadecimal colour");
  return {
    ...appearance(item.appearance, `${path}.appearance`),
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
    "brokers",
    "devices",
    "readings",
    "groups",
    "topic_appearances",
  ]);
  if (item.format !== "aberration-system" || item.schema_version !== 1)
    fail("system", "expected aberration-system schema version 1");
  const document: SystemDocument = {
    format: "aberration-system",
    schema_version: 1,
    label: text(item.label, "label", 120).trim(),
    default_policy: policy(item.default_policy, "default_policy"),
    brokers: list(item.brokers, "brokers", 128).map(connection),
    devices: list(item.devices, "devices", 2048).map(device),
    readings: list(item.readings, "readings", 4096).map(stream),
    groups: list(item.groups, "groups", 128).map(group),
    ...(item.topic_appearances === undefined ? {} : {
      topic_appearances: list(item.topic_appearances, "topic_appearances", 8192).map(topicAppearance),
    }),
  };
  const allIds = new Set<string>();
  for (const entity of [
    ...document.brokers,
    ...document.devices,
    ...document.readings,
    ...document.groups,
  ]) {
    if (allIds.has(entity.id)) fail("id", `duplicate identity ${entity.id}`);
    allIds.add(entity.id);
  }
  const connectionIds = new Set(document.brokers.map((entry) => entry.id));
  const topicKeys = new Set<string>();
  for (const entry of document.topic_appearances ?? []) {
    const key = JSON.stringify([entry.broker_id, entry.topic]);
    if (!connectionIds.has(entry.broker_id)) fail("topic appearance", "broker does not exist");
    if (topicKeys.has(key)) fail("topic appearance", "duplicate broker and topic");
    topicKeys.add(key);
  }
  const devices = new Map(document.devices.map((entry) => [entry.id, entry]));
  for (const entry of document.devices) {
    if (entry.broker_id && !connectionIds.has(entry.broker_id))
      fail(`device ${entry.id}`, "broker does not exist");
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
  const polled = new Set(
    document.brokers
      .filter((entry) => entry.protocol === "http")
      .map((entry) => entry.id),
  );
  for (const entry of document.readings) {
    if (!connectionIds.has(entry.broker_id))
      fail(`reading ${entry.id}`, "broker does not exist");
    if (entry.device_id && !devices.has(entry.device_id))
      fail(`stream ${entry.id}`, "device does not exist");
    if (!polled.has(entry.broker_id)) {
      if (entry.timestamp_pointer !== undefined)
        fail(`reading ${entry.id}`, "only an HTTP reading has a source timestamp");
    } else if (!entry.topic.startsWith("/") || hasControl(entry.topic, true))
      fail(
        `reading ${entry.id}`,
        "use a request path that starts with / and has no spaces",
      );
  }
  const memberIds = new Set(
    [...document.brokers, ...document.devices, ...document.readings].map(
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

/** Files saved before the API said brokers and readings use the older names. */
const LEGACY_NAMES: Record<string, string> = { connections: "brokers", streams: "readings", connection_id: "broker_id" };
function currentNames(value: unknown, depth = 0): unknown {
  if (Array.isArray(value)) return value.map((item) => currentNames(item, depth + 1));
  if (!record(value) || depth > 2) return value;
  return Object.fromEntries(Object.entries(value).map(([key, item]) =>
    [LEGACY_NAMES[key] ?? key, currentNames(item, depth + 1)]));
}

export function parseSystemDocument(contents: string): SystemDocument {
  return validateSystemDocument(currentNames(parseJson(contents)));
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
    default_policy: { ...DEFAULT_POLICY },
    brokers: [],
    devices: [],
    readings: [],
    groups: [],
  };
}

export const collectionByKind = {
  connection: "brokers",
  device: "devices",
  stream: "readings",
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
      .filter((entry) => entry.broker_id === entityId)
      .forEach((entry) => removal.add(entry.id));
    document.readings
      .filter((entry) => entry.broker_id === entityId)
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
    document.readings
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
    brokers: document.brokers.filter((entry) => !removed.has(entry.id)),
    ...(document.topic_appearances ? {
      topic_appearances: document.topic_appearances.filter(entry => !removed.has(entry.broker_id)),
    } : {}),
    devices: document.devices.filter((entry) => !removed.has(entry.id)),
    readings: document.readings.filter((entry) => !removed.has(entry.id)),
    groups: document.groups
      .filter((entry) => !removed.has(entry.id))
      .map((entry) => ({
        ...entry,
        member_ids: entry.member_ids.filter((member) => !removed.has(member)),
      })),
  });
}

export const ENTITY_NOUN = { connection: "connection", device: "device", stream: "stream", group: "collection" } as const;
type SystemEntity = SystemConnection | SystemDevice | SystemStream | SystemGroup;

/** A new, unsaved catalogue object with the editor's defaults. */
export function newSystemEntity(document: SystemDocument, kind: SystemEntityKind): SystemEntity {
  const identity = { id: `${kind}:${crypto.randomUUID()}`, label: `New ${ENTITY_NOUN[kind]}` };
  switch (kind) {
    case "connection":
      return { ...identity, host: "", ...connectionDefaults("mqtt") };
    case "device":
      return { ...identity, kind: "device", broker_id: document.brokers[0]?.id };
    case "stream":
      return { ...identity, broker_id: document.brokers[0]?.id ?? "", topic: "", value_type: "number",
        category: "Other", policy: { ...DEFAULT_POLICY } };
    case "group":
      return { ...identity, color: DEFAULT_GROUP_COLOR, member_ids: [] };
  }
}

/**
 * Save one edited object: an existing one is replaced in place, a new one is
 * appended. A group takes its members from every other group, and a device
 * that moves broker takes along the readings that were on its old broker.
 */
export function upsertSystemEntity(baseline: SystemDocument, kind: SystemEntityKind, entity: SystemEntity): SystemDocument {
  const key = collectionByKind[kind];
  const collection = baseline[key] as SystemEntity[];
  const exists = collection.some((item) => item.id === entity.id);
  const values = exists ? collection.map((item) => (item.id === entity.id ? entity : item)) : [...collection, entity];
  const candidate = { ...baseline, [key]: values };
  if (kind === "group") {
    const members = new Set((entity as SystemGroup).member_ids);
    candidate.groups = (values as SystemGroup[]).map((item) => item.id === entity.id ? item
      : { ...item, member_ids: item.member_ids.filter((id) => !members.has(id)) });
  }
  const device = entity as SystemDevice;
  const previous = kind === "device" ? baseline.devices.find((item) => item.id === entity.id) : undefined;
  if (previous && device.broker_id && device.broker_id !== previous.broker_id) {
    candidate.readings = baseline.readings.map((item) => item.device_id === entity.id && item.broker_id === previous.broker_id
      ? { ...item, broker_id: device.broker_id! } : item);
  }
  return validateSystemDocument(candidate);
}
