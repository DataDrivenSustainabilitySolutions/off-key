import type {
  NodeTelemetry,
  SpatialGroup,
  SpatialTelemetry,
  TelemetryMessage,
  Topology,
} from "./types";

export const MAX_CATALOG_BYTES = 1_000_000;
type ValueType = "number" | "boolean" | "text" | "identifier";
type CollectionMode = "off" | "original" | "sample";
type Policy = { mode: CollectionMode; intervalSeconds: number };
type Sensor = {
  key: string;
  label: string;
  category: string;
  valueType: ValueType;
  unit: string;
  upstreamTopic: string;
  policy: Policy | null;
};
type Charger = {
  id: string;
  localId: string;
  label: string;
  policy: Policy | null;
  sensors: Sensor[];
};
type Source = { id: string; label: string; chargers: Charger[] };
export type SpatialCatalogSummary = {
  brokers: number;
  chargers: number;
  streams: number;
  valueTypes: Record<ValueType, number>;
  categories: Record<string, number>;
  collectionModes: Record<CollectionMode, number>;
};
export type SpatialCatalogProjection = {
  topology: Topology;
  groups: SpatialGroup[];
  summary: SpatialCatalogSummary;
  datasetKey: string;
};

const COLORS = ["#0e8174", "#7561b7", "#ca8a25", "#4779b4", "#b0617c"];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
function invalid(reason: string): never {
  // Never interpolate supplied values: imports may contain private identities.
  throw new Error(`Invalid AmbiBox catalog: ${reason}.`);
}
function object(value: unknown): Record<string, unknown> {
  return record(value) ? value : invalid("expected an object");
}
function text(value: unknown, max: number): string {
  return typeof value === "string" &&
    value.length > 0 &&
    value.length <= max &&
    !value.includes("\0")
    ? value
    : invalid("invalid text field");
}
function uuid(value: unknown): string {
  const id = text(value, 36);
  return UUID.test(id)
    ? id.toLowerCase()
    : invalid("invalid stable identifier");
}
function list(value: unknown, max: number): unknown[] {
  return Array.isArray(value) && value.length <= max
    ? value
    : invalid("invalid collection size");
}
function policy(value: unknown, nullable = false): Policy | null {
  if (nullable && (value === undefined || value === null)) return null;
  const raw = object(value);
  if (raw.mode !== "off" && raw.mode !== "original" && raw.mode !== "sample")
    invalid("invalid collection mode");
  if (
    !Number.isInteger(raw.interval_seconds) ||
    Number(raw.interval_seconds) < 1 ||
    Number(raw.interval_seconds) > 3600
  )
    invalid("invalid collection interval");
  return { mode: raw.mode, intervalSeconds: Number(raw.interval_seconds) };
}
function unique(values: string[], reason: string) {
  if (new Set(values).size !== values.length) invalid(reason);
}

/** Synchronous, deterministic fingerprint; collisions are checked during projection. */
function fingerprint(value: string): string {
  let first = 0x811c9dc5;
  let second = 0x9e3779b9;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    first = Math.imul(first ^ code, 0x01000193);
    second = Math.imul(second ^ code, 0x85ebca6b);
    second ^= second >>> 13;
  }
  return `${(first >>> 0).toString(16).padStart(8, "0")}${(second >>> 0).toString(16).padStart(8, "0")}`;
}
function sensorId(chargerId: string, key: string): string {
  const prefix = `ambibox:sensor:${chargerId}:`;
  // Preserve short keys exactly; nested/long keys need bounded storage-safe IDs.
  return /^[\w.-]+$/.test(key) && prefix.length + key.length <= 128
    ? prefix + key
    : prefix + "key-" + fingerprint(JSON.stringify([chargerId, key]));
}

/** Read-only import: copy presentation metadata, never broker endpoints or secrets. */
export function parseSpatialCatalog(
  contents: string,
): SpatialCatalogProjection {
  return parseProjection(contents, false);
}

/** Restore only the stripped presentation format produced below. */
export function restoreSpatialCatalog(
  contents: string,
): SpatialCatalogProjection {
  return parseProjection(contents, true);
}

function parseProjection(
  contents: string,
  presentationOnly: boolean,
): SpatialCatalogProjection {
  if (
    contents.length > MAX_CATALOG_BYTES ||
    new TextEncoder().encode(contents).byteLength > MAX_CATALOG_BYTES
  )
    invalid("file exceeds 1 MB");
  let parsed: unknown;
  try {
    parsed = JSON.parse(contents);
  } catch {
    invalid("expected valid JSON");
  }
  const raw = object(parsed);
  if (raw.schema_version !== 1 || raw.provider !== "ambibox")
    invalid("unsupported schema or provider");
  if (presentationOnly && raw.format !== "aberration-spatial-catalog-v1")
    invalid("unsupported presentation format");
  const defaultPolicy = policy(raw.default_policy)!;
  const endpoints: string[] = [];
  let streamCount = 0;
  const sources: Source[] = list(raw.sources, 128)
    .map((value) => {
      const source = object(value);
      if (!presentationOnly) {
        const host = text(source.host, 253).toLowerCase().replace(/\.$/, "");
        const labelPattern = "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?";
        if (!new RegExp(`^${labelPattern}(?:\\.${labelPattern})*$`).test(host))
          invalid("invalid broker hostname");
        const port = source.port ?? 1883;
        if (!Number.isInteger(port) || Number(port) < 1 || Number(port) > 65535)
          invalid("invalid broker port");
        endpoints.push(`${host}:${port}`);
      }
      const chargers: Charger[] = list(source.chargers, 16).map((value) => {
        const charger = object(value);
        const localId = text(charger.local_id, 80);
        if (!/^[\w-]+$/.test(localId))
          invalid("invalid charger local identifier");
        const sensors: Sensor[] = list(charger.sensors, 128).map((value) => {
          const sensor = object(value);
          const key = text(sensor.key, 160);
          if (!/^[\p{L}\p{N}_-]+(?:\/[\p{L}\p{N}_-]+)*$/u.test(key))
            invalid("invalid sensor key");
          const upstreamTopic = text(sensor.upstream_topic, 512);
          if (
            !/^[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*$/.test(upstreamTopic) ||
            !upstreamTopic.startsWith(`device/evCharger/${localId}/`)
          )
            invalid("invalid concrete sensor topic");
          const valueType = sensor.value_type ?? "number";
          if (
            valueType !== "number" &&
            valueType !== "boolean" &&
            valueType !== "text" &&
            valueType !== "identifier"
          )
            invalid("invalid sensor value type");
          const unit =
            sensor.unit === null ||
            sensor.unit === undefined ||
            sensor.unit === ""
              ? ""
              : text(sensor.unit, 32);
          streamCount += 1;
          if (streamCount > 4096) invalid("more than 4096 streams");
          return {
            key,
            label: text(sensor.label, 120),
            category: text(sensor.category ?? "Other", 60),
            valueType,
            unit,
            upstreamTopic,
            policy: policy(sensor.policy, true),
          };
        });
        unique(
          sensors.map((sensor) => sensor.key),
          "duplicate sensor keys",
        );
        unique(
          sensors.map((sensor) => sensor.upstreamTopic),
          "duplicate sensor topics",
        );
        return {
          id: uuid(charger.id),
          localId,
          label: text(charger.label, 120),
          policy: policy(charger.policy, true),
          sensors: sensors.sort((a, b) => a.key.localeCompare(b.key)),
        };
      });
      unique(
        chargers.map((charger) => charger.localId),
        "duplicate charger local identifiers",
      );
      return {
        id: uuid(source.id),
        label: text(source.label, 120),
        chargers: chargers.sort((a, b) => a.id.localeCompare(b.id)),
      };
    })
    .sort((a, b) => a.id.localeCompare(b.id));
  unique(
    sources.map((source) => source.id),
    "duplicate broker identifiers",
  );
  unique(endpoints, "duplicate broker endpoints");
  const chargers = sources.flatMap((source) => source.chargers);
  unique(
    chargers.map((charger) => charger.id),
    "duplicate charger identifiers",
  );
  return project(sources, defaultPolicy, streamCount);
}

/** Retain imported presentation across reloads without copying endpoints or secrets. */
export function serializeSpatialCatalog(
  projection: SpatialCatalogProjection,
): string {
  const { nodes } = projection.topology;
  const sources = nodes
    .filter((node) => node.kind === "broker")
    .map((broker) => ({
      id: broker.catalog?.sourceId,
      label: broker.label,
      chargers: nodes
        .filter(
          (node) =>
            node.kind === "charger" &&
            node.catalog?.sourceId === broker.catalog?.sourceId,
        )
        .map((charger) => ({
          id: charger.catalog?.chargerId,
          local_id: charger.catalog?.localId,
          label: charger.label,
          policy: {
            mode: charger.catalog?.collectionMode,
            interval_seconds: charger.catalog?.intervalSeconds,
          },
          sensors: nodes
            .filter(
              (node) =>
                node.kind === "sensor" &&
                node.catalog?.chargerId === charger.catalog?.chargerId,
            )
            .map((sensor) => ({
              key: sensor.catalog?.sensorKey,
              label: sensor.label,
              category: sensor.catalog?.category,
              value_type: sensor.catalog?.valueType,
              unit: sensor.unit || null,
              upstream_topic: sensor.catalog?.upstreamTopic,
              policy: {
                mode: sensor.catalog?.collectionMode,
                interval_seconds: sensor.catalog?.intervalSeconds,
              },
            })),
        })),
    }));
  return JSON.stringify({
    format: "aberration-spatial-catalog-v1",
    schema_version: 1,
    provider: "ambibox",
    default_policy: { mode: "off", interval_seconds: 10 },
    sources,
  });
}

function project(
  sources: Source[],
  defaultPolicy: Policy,
  streamCount: number,
): SpatialCatalogProjection {
  const topology: Topology = { nodes: [], edges: [] };
  const groups: SpatialGroup[] = [];
  const summary: SpatialCatalogSummary = {
    brokers: sources.length,
    chargers: sources.reduce(
      (total, source) => total + source.chargers.length,
      0,
    ),
    streams: streamCount,
    valueTypes: { number: 0, boolean: 0, text: 0, identifier: 0 },
    categories: {},
    collectionModes: { off: 0, original: 0, sample: 0 },
  };
  const categories = new Map<string, number>();
  const count = sources.reduce(
    (total, source) => total + Math.max(1, source.chargers.length),
    0,
  );
  if (count > 128) invalid("more than 128 charger collections in this preview");
  const columns = Math.min(6, Math.max(1, count));
  const rows = Math.ceil(count / columns);
  const maxSensors = Math.max(
    0,
    ...sources.flatMap((source) =>
      source.chargers.map((charger) => charger.sensors.length),
    ),
  );
  const spacing = Math.max(25, Math.ceil(Math.sqrt(maxSensors)) * 2.8 + 9);
  let slot = 0;
  for (const source of sources) {
    const brokerId = `ambibox:broker:${source.id}`;
    const firstGroup = `ambibox:group:${source.chargers[0]?.id ?? source.id}`;
    const localChargers = source.chargers.length ? source.chargers : [null];
    for (const charger of localChargers) {
      const groupId = `ambibox:group:${charger?.id ?? source.id}`;
      const center = {
        x: ((slot % columns) - (columns - 1) / 2) * spacing,
        z: (Math.floor(slot / columns) - (rows - 1) / 2) * spacing,
      };
      groups.push({
        id: groupId,
        name: (charger?.label ?? source.label).slice(0, 80),
        color: COLORS[slot % COLORS.length]!,
        collapsed: true,
        locked: false,
      });
      if (groupId === firstGroup) {
        topology.nodes.push({
          id: brokerId,
          label: source.label,
          kind: "broker",
          groupId,
          position: { x: center.x, z: center.z - 8 },
          locked: false,
          unit: "msg/s",
          metric: "Throughput",
          baseRate: 0,
          catalog: { sourceId: source.id },
        });
      }
      if (charger) {
        const chargerPolicy = charger.policy ?? defaultPolicy;
        topology.nodes.push({
          id: `ambibox:charger:${charger.id}`,
          label: charger.label,
          kind: "charger",
          brokerId,
          groupId,
          position: { x: center.x, z: center.z - 4 },
          locked: false,
          unit: "",
          metric: "Charger",
          baseRate: 0,
          catalog: {
            sourceId: source.id,
            chargerId: charger.id,
            localId: charger.localId,
            collectionMode: chargerPolicy.mode,
            intervalSeconds: chargerPolicy.intervalSeconds,
          },
        });
        const sensorColumns = Math.max(
          1,
          Math.ceil(Math.sqrt(charger.sensors.length)),
        );
        charger.sensors.forEach((sensor, index) => {
          const id = sensorId(charger.id, sensor.key);
          const effectivePolicy =
            sensor.policy ?? charger.policy ?? defaultPolicy;
          topology.nodes.push({
            id,
            label: sensor.label,
            kind: "sensor",
            brokerId,
            groupId,
            position: {
              x:
                center.x +
                ((index % sensorColumns) - (sensorColumns - 1) / 2) * 2.8,
              z: center.z + Math.floor(index / sensorColumns) * 2.8,
            },
            locked: false,
            unit: sensor.unit,
            metric: sensor.label,
            baseRate: 0,
            catalog: {
              sourceId: source.id,
              chargerId: charger.id,
              localId: charger.localId,
              sensorKey: sensor.key,
              upstreamTopic: sensor.upstreamTopic,
              valueType: sensor.valueType,
              collectionMode: effectivePolicy.mode,
              intervalSeconds: effectivePolicy.intervalSeconds,
              category: sensor.category,
            },
          });
          // Only actual MQTT routes are connections; containment uses group tiles.
          topology.edges.push({
            id: `edge:${id}`,
            source: id,
            target: brokerId,
          });
          summary.valueTypes[sensor.valueType] += 1;
          summary.collectionModes[effectivePolicy.mode] += 1;
          categories.set(
            sensor.category,
            (categories.get(sensor.category) ?? 0) + 1,
          );
        });
      }
      slot += 1;
    }
  }
  unique(
    groups.map((group) => group.id),
    "colliding collection identifiers",
  );
  unique(
    topology.nodes.map((node) => node.id),
    "colliding presentation identifiers",
  );
  summary.categories = Object.fromEntries(categories);
  return {
    topology,
    groups,
    summary,
    datasetKey: `ambibox-${fingerprint(JSON.stringify(topology.nodes.map((node) => node.id).sort()))}`,
  };
}

/** Catalog metadata alone is not evidence that a message has arrived. */
export class PassiveCatalogTelemetry implements SpatialTelemetry {
  start() {}
  dispose() {}
  setPaused(paused: boolean) {
    void paused;
  }
  getSnapshot(id: string): NodeTelemetry | undefined {
    void id;
    return undefined;
  }
  subscribe(listener: (message: TelemetryMessage) => void): () => void {
    void listener;
    return () => undefined;
  }
}
