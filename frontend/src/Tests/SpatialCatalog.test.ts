import { describe, expect, it, vi } from "vitest";
import {
  MAX_CATALOG_BYTES,
  parseSpatialCatalog,
  PassiveCatalogTelemetry,
  restoreSpatialCatalog,
  serializeSpatialCatalog,
} from "@/features/spatial/catalog";
import {
  createDefaultWorkspace,
  resolveTopology,
} from "@/features/spatial/model";

// Synthetic identities only: the private preset must never become a test fixture.
const id = (index: number) =>
  `00000000-0000-4000-8000-${index.toString(16).padStart(12, "0")}`;
function sensor(index: number, localId = "0") {
  return {
    key: `reading-${index}`,
    label: `Metric ${index}`,
    category: "Measurements",
    value_type:
      index < 18
        ? "number"
        : index < 20
          ? "boolean"
          : index < 22
            ? "text"
            : index === 22
              ? "identifier"
              : "boolean",
    unit: null,
    upstream_topic: `device/evCharger/${localId}/reading-${index}`,
    policy: null,
  };
}
function source(index: number, sensorCount = 23) {
  return {
    id: id(1000 + index),
    label: `Example broker ${index}`,
    host: `broker-${index}.example.invalid`,
    port: 1883,
    verified: false,
    forward_port: 20000 + index,
    password: "example-credential-must-be-stripped",
    chargers: [
      {
        id: id(2000 + index),
        local_id: "0",
        label: `Example charger ${index}`,
        policy: { mode: "off", interval_seconds: 10 },
        sensors: Array.from({ length: sensorCount }, (_, index) =>
          sensor(index),
        ),
      },
    ],
  };
}
function catalog(sourceCount = 1) {
  return {
    schema_version: 1,
    provider: "ambibox",
    default_policy: { mode: "sample", interval_seconds: 10 },
    sources: Array.from({ length: sourceCount }, (_, index) => source(index)),
  };
}
const importCatalog = (value: unknown) =>
  parseSpatialCatalog(JSON.stringify(value));

describe("read-only spatial catalog projection", () => {
  it("represents fleet scale and value types without manufacturing data or subscriptions", () => {
    const input = catalog(31);
    input.sources[30]!.chargers[0]!.sensors.push(sensor(23));
    const result = importCatalog(input);
    expect(result.summary).toMatchObject({
      brokers: 31,
      chargers: 31,
      streams: 714,
      valueTypes: { number: 558, boolean: 63, text: 62, identifier: 31 },
      collectionModes: { off: 714, original: 0, sample: 0 },
    });
    expect(result.topology.nodes).toHaveLength(776);
    expect(result.topology.edges).toHaveLength(714);
    expect(result.groups).toHaveLength(31);
    expect(result.groups.every((group) => group.collapsed)).toBe(true);
    expect(result.topology.nodes.every((node) => node.baseRate === 0)).toBe(
      true,
    );
    expect(
      result.topology.nodes
        .filter((node) => node.kind === "sensor")
        .every((node) => node.unit === ""),
    ).toBe(true);
    const nodes = new Map(result.topology.nodes.map((node) => [node.id, node]));
    expect(
      result.topology.edges.every(
        (edge) =>
          nodes.get(edge.source)?.kind === "sensor" &&
          nodes.get(edge.target)?.kind === "broker",
      ),
    ).toBe(true);
    const workspace = { ...createDefaultWorkspace(), groups: result.groups };
    expect(resolveTopology(result.topology, workspace).nodes).toHaveLength(31);
  });

  it("retains exact stable bindings when catalog order or visual membership changes", () => {
    const input = catalog(2);
    const before = importCatalog(input);
    input.sources.reverse();
    input.sources.forEach((source) => source.chargers[0]!.sensors.reverse());
    const after = importCatalog(input);
    expect(after).toEqual(before);
    const stream = after.topology.nodes.find((node) => node.kind === "sensor")!;
    expect(stream.id).toBe(
      `ambibox:sensor:${stream.catalog?.chargerId}:${stream.catalog?.sensorKey}`,
    );
    const workspace = {
      ...createDefaultWorkspace(),
      groups: after.groups.map((group) => ({ ...group, collapsed: false })),
      memberships: { [stream.id]: after.groups[1]!.id },
    };
    const resolved = resolveTopology(after.topology, workspace);
    expect(
      resolved.nodes.find((node) => node.id === stream.id)?.catalog,
    ).toEqual(stream.catalog);
    expect(
      resolved.edges.find((edge) => edge.source === stream.id)?.target,
    ).toBe(stream.brokerId);
    input.sources[0]!.label = "Renamed broker";
    expect(importCatalog(input).datasetKey).toBe(before.datasetKey);
  });

  it("handles several chargers on one source with separate containment and unchanged direct routes", () => {
    const input = catalog();
    const second = source(1).chargers[0]!;
    second.local_id = "1";
    second.sensors = second.sensors.map((entry, index) => ({
      ...entry,
      ...sensor(index, "1"),
    }));
    input.sources[0]!.chargers.push(second);
    const result = importCatalog(input);
    expect(result.summary).toMatchObject({
      brokers: 1,
      chargers: 2,
      streams: 46,
    });
    expect(result.groups).toHaveLength(2);
    expect(new Set(result.topology.edges.map((edge) => edge.target)).size).toBe(
      1,
    );
    expect(
      result.topology.nodes
        .filter((node) => node.kind === "charger")
        .every(
          (node) =>
            node.brokerId ===
            result.topology.nodes.find((node) => node.kind === "broker")?.id,
        ),
    ).toBe(true);
  });

  it("resolves sensor override, charger override and fleet policy in that order", () => {
    const input = catalog();
    const charger = input.sources[0]!.chargers[0]!;
    // A nullable inherited policy is valid catalog input.
    const inherited = {
      ...charger,
      policy: null,
      sensors: [
        { ...sensor(0), policy: { mode: "original", interval_seconds: 5 } },
        sensor(1),
      ],
    };
    const result = importCatalog({
      ...input,
      sources: [{ ...input.sources[0], chargers: [inherited] }],
    });
    expect(result.summary.collectionModes).toEqual({
      off: 0,
      original: 1,
      sample: 1,
    });
    expect(
      result.topology.nodes.find(
        (node) => node.catalog?.sensorKey === "reading-0",
      )?.catalog,
    ).toMatchObject({ collectionMode: "original", intervalSeconds: 5 });
    expect(
      result.topology.nodes.find(
        (node) => node.catalog?.sensorKey === "reading-1",
      )?.catalog,
    ).toMatchObject({ collectionMode: "sample", intervalSeconds: 10 });
  });

  it("uses bounded collision-checked IDs for nested and long keys", () => {
    const input = catalog();
    const charger = input.sources[0]!.chargers[0]!;
    charger.sensors = [{ ...sensor(0), key: `nested/${"a".repeat(145)}` }];
    const result = importCatalog(input);
    const stream = result.topology.nodes.find(
      (node) => node.kind === "sensor",
    )!;
    expect(stream.id).toMatch(/^[\w:.-]{1,128}$/);
    expect(stream.catalog?.sensorKey).toBe(charger.sensors[0]!.key);
    const collidingKey = stream.id.slice(stream.id.lastIndexOf(":") + 1);
    charger.sensors.push({ ...sensor(1), key: collidingKey });
    expect(() => importCatalog(input)).toThrow(
      "colliding presentation identifiers",
    );
  });

  it("keeps endpoints, credentials and runtime values out of persisted presentation", () => {
    const input = catalog(2);
    const projection = importCatalog(input);
    const exposed = JSON.stringify(projection);
    const stored = serializeSpatialCatalog(projection);
    for (const text of [
      "broker-0.example.invalid",
      "example-credential-must-be-stripped",
      "forward_port",
      '"host"',
      '"port"',
      '"password"',
    ]) {
      expect(exposed).not.toContain(text);
      expect(stored).not.toContain(text);
    }
    expect(stored).not.toContain('"samples"');
    expect(stored).not.toContain('"received"');
    expect(restoreSpatialCatalog(stored)).toEqual(projection);
    expect(() => restoreSpatialCatalog(JSON.stringify(input))).toThrow(
      "unsupported presentation format",
    );
    const corrupt = JSON.parse(stored);
    corrupt.sources[0].chargers[0].sensors[0].value_type = "arbitrary";
    expect(() => restoreSpatialCatalog(JSON.stringify(corrupt))).toThrow(
      "invalid sensor value type",
    );
  });

  it("rejects malformed imports atomically with errors that do not disclose input", () => {
    expect(() => parseSpatialCatalog("broken JSON")).toThrow(
      "expected valid JSON",
    );
    expect(() =>
      parseSpatialCatalog(" ".repeat(MAX_CATALOG_BYTES + 1)),
    ).toThrow("exceeds 1 MB");
    expect(() => parseSpatialCatalog('"' + "雪".repeat(400_000) + '"')).toThrow(
      "exceeds 1 MB",
    );
    expect(() => importCatalog({ ...catalog(), schema_version: 2 })).toThrow(
      "unsupported schema",
    );
    const input = catalog();
    input.sources[0]!.id = "private-identity-not-for-errors";
    expect(() => importCatalog(input)).toThrow("invalid stable identifier");
    try {
      importCatalog(input);
    } catch (error) {
      expect(String(error)).not.toContain(input.sources[0]!.id);
    }
  });

  it("rejects ambiguous routing and identity collisions", () => {
    const duplicateSource = catalog(2);
    duplicateSource.sources[1]!.id = duplicateSource.sources[0]!.id;
    expect(() => importCatalog(duplicateSource)).toThrow(
      "duplicate broker identifiers",
    );
    const duplicateEndpoint = catalog(2);
    duplicateEndpoint.sources[1]!.host = duplicateEndpoint.sources[0]!.host;
    expect(() => importCatalog(duplicateEndpoint)).toThrow(
      "duplicate broker endpoints",
    );
    const duplicateCharger = catalog(2);
    duplicateCharger.sources[1]!.chargers[0]!.id =
      duplicateCharger.sources[0]!.chargers[0]!.id;
    expect(() => importCatalog(duplicateCharger)).toThrow(
      "duplicate charger identifiers",
    );
    const duplicateKey = catalog();
    duplicateKey.sources[0]!.chargers[0]!.sensors[1]!.key = "reading-0";
    expect(() => importCatalog(duplicateKey)).toThrow("duplicate sensor keys");
    const duplicateTopic = catalog();
    duplicateTopic.sources[0]!.chargers[0]!.sensors[1]!.upstream_topic =
      "device/evCharger/0/reading-0";
    expect(() => importCatalog(duplicateTopic)).toThrow(
      "duplicate sensor topics",
    );
    const wildcard = catalog();
    wildcard.sources[0]!.chargers[0]!.sensors[0]!.upstream_topic =
      "device/evCharger/0/#";
    expect(() => importCatalog(wildcard)).toThrow(
      "invalid concrete sensor topic",
    );
    const mismatchedCharger = catalog();
    mismatchedCharger.sources[0]!.chargers[0]!.sensors[0]!.upstream_topic =
      "device/evCharger/other/reading-0";
    expect(() => importCatalog(mismatchedCharger)).toThrow(
      "invalid concrete sensor topic",
    );
  });

  it("enforces the preview's source, stream and collection budgets", () => {
    expect(() => importCatalog(catalog(129))).toThrow(
      "invalid collection size",
    );
    const streams = catalog(33);
    streams.sources.forEach((entry) => {
      entry.chargers[0]!.sensors = Array.from({ length: 128 }, (_, index) =>
        sensor(index),
      );
    });
    expect(() => importCatalog(streams)).toThrow("more than 4096 streams");
    const groups = catalog(128);
    groups.sources[0]!.chargers.push({
      ...source(129, 0).chargers[0]!,
      local_id: "other",
    });
    expect(() => importCatalog(groups)).toThrow(
      "more than 128 charger collections",
    );
  });

  it("does not present static catalog metadata as received telemetry", () => {
    const telemetry = new PassiveCatalogTelemetry();
    const listener = vi.fn();
    const unsubscribe = telemetry.subscribe(listener);
    telemetry.start();
    telemetry.setPaused(false);
    expect(telemetry.getSnapshot("any-node")).toBeUndefined();
    expect(listener).not.toHaveBeenCalled();
    unsubscribe();
    telemetry.dispose();
    telemetry.start();
    expect(telemetry.getSnapshot("any-node")).toBeUndefined();
  });
});
