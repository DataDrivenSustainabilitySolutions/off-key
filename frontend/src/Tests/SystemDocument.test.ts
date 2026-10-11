import { describe, expect, it } from "vitest";
import { parseSpatialCatalog } from "@/features/spatial/catalog";
import {
  createEmptySystem,
  importSystemDocument,
  parseSystemDocument,
  removeSystemEntity,
  renameSystemEntity,
  serializeSystemDocument,
  systemRemovalIds,
  validateSystemDocument,
} from "@/features/spatial/systemDocument";
import {
  createDefaultWorkspace,
  moveNodes,
  resolveTopology,
} from "@/features/spatial/model";
import {
  projectSystemDocument,
  reconcileSystemWorkspace,
} from "@/features/spatial/systemProjection";
import type { SystemDocument } from "@/features/spatial/systemTypes";

export const systemFixture = (): SystemDocument => ({
  ...createEmptySystem("Workshop"),
  connections: [
    {
      id: "connection:workshop",
      label: "Workshop broker",
      protocol: "mqtt",
      host: "broker.example.test",
      port: 1883,
      transport: "tcp",
      tls: false,
      credential_ref: "secrets/workshop",
    },
  ],
  devices: [
    {
      id: "device:oven",
      label: "Oven",
      kind: "oven",
      connection_id: "connection:workshop",
    },
    {
      id: "device:probe",
      label: "Probe",
      kind: "sensor",
      parent_id: "device:oven",
    },
  ],
  streams: [
    {
      id: "stream:temperature",
      label: "Temperature",
      connection_id: "connection:workshop",
      device_id: "device:probe",
      topic: "workshop/oven/measurements",
      payload_pointer: "/temperature",
      value_type: "number",
      category: "Environment",
      unit: "°C",
      policy: { mode: "sample", interval_seconds: 20 },
    },
  ],
  groups: [
    {
      id: "group:workshop",
      label: "Workshop",
      color: "#0e8174",
      member_ids: [
        "connection:workshop",
        "device:oven",
        "device:probe",
        "stream:temperature",
      ],
    },
  ],
});

describe("domain agnostic saved systems", () => {
  it("roundtrips connection access, structure and stream bindings independently of a domain", () => {
    const system = systemFixture();
    expect(parseSystemDocument(serializeSystemDocument(system))).toEqual(
      system,
    );
    expect(importSystemDocument(serializeSystemDocument(system))).toEqual(
      system,
    );
    expect(serializeSystemDocument(system)).not.toMatch(
      /charger|ambibox|password/,
    );
  });

  it("accepts nullable optional fields returned by the backend without storing null placeholders", () => {
    const system = systemFixture();
    const response = {
      ...system,
      connections: system.connections.map((entry) => ({
        ...entry,
        websocket_path: null,
      })),
      devices: system.devices.map((entry) => ({
        ...entry,
        parent_id: entry.parent_id ?? null,
        connection_id: entry.connection_id ?? null,
      })),
      streams: system.streams.map((entry) => ({
        ...entry,
        unit: null,
        payload_pointer: null,
        policy: null,
      })),
    };
    const parsed = validateSystemDocument(response);
    expect(parsed.connections[0]).not.toHaveProperty("websocket_path");
    expect(parsed.streams[0]).not.toHaveProperty("policy");
  });

  it.each([
    (system: SystemDocument) => ({ ...system, password: "secret" }),
    (system: SystemDocument) => ({
      ...system,
      connections: [{ ...system.connections[0], password: "secret" }],
    }),
    (system: SystemDocument) => ({
      ...system,
      streams: [{ ...system.streams[0], connection_id: "missing" }],
    }),
    (system: SystemDocument) => ({
      ...system,
      streams: [{ ...system.streams[0], topic: "workshop/#" }],
    }),
    (system: SystemDocument) => ({
      ...system,
      streams: [{ ...system.streams[0], topic: "💧".repeat(129) }],
    }),
    (system: SystemDocument) => ({
      ...system,
      streams: [{ ...system.streams[0], payload_pointer: "/invalid~escape" }],
    }),
    (system: SystemDocument) => ({
      ...system,
      devices: [
        { ...system.devices[0], parent_id: "device:probe" },
        system.devices[1],
      ],
    }),
    (system: SystemDocument) => ({
      ...system,
      groups: [
        ...system.groups,
        { id: "duplicate", label: "Second", member_ids: ["device:oven"] },
      ],
    }),
    (system: SystemDocument) => ({
      ...system,
      groups: [{ ...system.groups[0], member_ids: ["missing"] }],
    }),
    (system: SystemDocument) => ({
      ...system,
      devices: [{ ...system.devices[0], id: "connection:workshop" }],
    }),
  ])(
    "rejects invalid graph bindings, cycles, secrets or ambiguous group membership",
    (mutate) => {
      expect(() => validateSystemDocument(mutate(systemFixture()))).toThrow();
    },
  );

  it("renames display names without changing identities or topics", () => {
    const before = systemFixture();
    const renamed = renameSystemEntity(
      before,
      "stream",
      "stream:temperature",
      "Room temperature",
    );
    expect(renamed.streams[0]).toEqual({
      ...before.streams[0],
      label: "Room temperature",
    });
    expect(before.streams[0]?.label).toBe("Temperature");
    expect(renamed.connections).toEqual(before.connections);
  });

  it("requires explicit cascade removal and removes dependent streams and group memberships together", () => {
    const before = systemFixture();
    expect(systemRemovalIds(before, "device", "device:oven")).toEqual([
      "device:oven",
      "device:probe",
      "stream:temperature",
    ]);
    expect(() => removeSystemEntity(before, "device", "device:oven")).toThrow(
      /dependent objects/,
    );
    const removed = removeSystemEntity(before, "device", "device:oven", true);
    expect(removed.devices).toEqual([]);
    expect(removed.streams).toEqual([]);
    expect(removed.groups[0]?.member_ids).toEqual(["connection:workshop"]);
    expect(removed.connections).toEqual(before.connections);
  });

  it("imports a legacy catalog as ordinary devices while preserving old layout identities and effective policies", () => {
    const sourceId = "00000000-0000-4000-8000-000000000001";
    const deviceId = "00000000-0000-4000-8000-000000000002";
    const legacy = {
      schema_version: 1,
      provider: "ambibox",
      default_policy: { mode: "original", interval_seconds: 10 },
      sources: [
        {
          id: sourceId,
          label: "Example broker",
          host: "broker.example.test",
          port: 1883,
          chargers: [
            {
              id: deviceId,
              local_id: "0",
              label: "Example device",
              policy: { mode: "off", interval_seconds: 10 },
              sensors: [
                {
                  key: "measurements/temperature",
                  label: "Temperature",
                  category: "Other",
                  value_type: "number",
                  unit: null,
                  upstream_topic: "device/evCharger/0/measurements/temperature",
                  policy: null,
                },
              ],
            },
          ],
        },
      ],
    };
    const contents = JSON.stringify(legacy);
    const imported = importSystemDocument(contents);
    expect(imported.devices[0]?.kind).toBe("device");
    expect(imported.streams[0]?.policy?.mode).toBe("off");
    expect(imported.streams[0]?.id).toBe(
      parseSpatialCatalog(contents).topology.nodes.find(
        (entry) => entry.kind === "sensor",
      )?.id,
    );
    expect(serializeSystemDocument(imported)).not.toContain('"provider"');
    expect(imported.connections[0]?.host).toBe("broker.example.test");
  });

  it("reconciles edited configuration into the view without dropping placement or camera", () => {
    const projection = projectSystemDocument(systemFixture());
    const saved = {
      ...projection.workspace,
      positions: {
        "stream:temperature": { x: 3, z: 5 },
        removed: { x: 0, z: 0 },
      },
      locks: { "stream:temperature": true },
      camera: {
        position: [10, 20, 30] as [number, number, number],
        target: [1, 2, 3] as [number, number, number],
        zoom: 2,
      },
      groups: projection.groups.map((entry) => ({
        ...entry,
        collapsed: false,
        locked: true,
        name: "Old browser label",
        color: "#ffffff",
      })),
    };
    const system = systemFixture();
    system.groups[0]!.label = "Canonical group";
    system.groups[0]!.color = "#aabbcc";
    const reconciled = reconcileSystemWorkspace(
      projectSystemDocument(system),
      saved,
    );
    expect(reconciled.positions["stream:temperature"]).toEqual({ x: 3, z: 5 });
    expect(reconciled.positions).not.toHaveProperty("removed");
    expect(Object.keys(reconciled.positions)).toHaveLength(
      projection.topology.nodes.length,
    );
    expect(reconciled.camera).toEqual(saved.camera);
    expect(reconciled.groups[0]).toMatchObject({
      name: "Canonical group",
      color: "#aabbcc",
      collapsed: false,
      locked: true,
    });
    expect(
      projection.topology.nodes.every((entry) => entry.baseRate === 0),
    ).toBe(true);
    expect(projection.topology.edges).toContainEqual({
      id: "stream:stream:temperature",
      source: "stream:temperature",
      target: "device:probe",
    });
  });

  it("seeds stable placement so adding objects cannot move previously unpositioned objects", () => {
    const before = projectSystemDocument(systemFixture());
    const saved = reconcileSystemWorkspace(before, before.workspace);
    const changed = systemFixture();
    changed.devices.unshift({
      id: "device:new",
      label: "New room",
      kind: "room",
    });
    const updated = reconcileSystemWorkspace(
      projectSystemDocument(changed),
      saved,
    );
    for (const node of before.topology.nodes)
      expect(updated.positions[node.id]).toEqual(saved.positions[node.id]);
    expect(updated.positions["device:new"]).toBeDefined();
  });

  it("supports ordinary prototype-name IDs without inheriting saved placement, locks or group membership", () => {
    const system = createEmptySystem();
    system.connections.push({
      id: "valueOf",
      label: "Connection",
      protocol: "mqtt",
      host: "broker.example.test",
      port: 1883,
      transport: "tcp",
      tls: false,
    });
    system.devices.push({
      id: "toString",
      label: "Device",
      kind: "device",
      connection_id: "valueOf",
    });
    system.streams.push({
      id: "hasOwnProperty",
      label: "Stream",
      connection_id: "valueOf",
      device_id: "toString",
      topic: "readings/value",
      value_type: "number",
      category: "Other",
    });
    const projection = projectSystemDocument(system);
    const empty = createDefaultWorkspace();
    const beforeReconcile = resolveTopology(projection.topology, empty);
    expect(
      beforeReconcile.nodes.every(
        (node) =>
          Number.isFinite(node.position.x) &&
          Number.isFinite(node.position.z) &&
          node.locked === false,
      ),
    ).toBe(true);
    const reconciled = reconcileSystemWorkspace(projection, empty);
    expect(reconciled.positions.toString).toEqual(
      projection.topology.nodes.find((node) => node.id === "toString")
        ?.position,
    );
    const moved = moveNodes(reconciled, { toString: { x: 8, z: 12 } });
    expect(
      resolveTopology(projection.topology, moved).nodes.find(
        (node) => node.id === "toString",
      )?.position,
    ).toEqual({ x: 8, z: 12 });
  });

  it("rejects physical IDs colliding with rendered aggregates while allowing unrelated group-prefixed IDs", () => {
    const system = createEmptySystem();
    system.devices.push({ id: "group:roof", label: "Device", kind: "device" });
    system.groups.push({
      id: "roof",
      label: "Roof",
      member_ids: ["group:roof"],
    });
    expect(() => validateSystemDocument(system)).toThrow(/collides/);
    system.groups = [];
    expect(validateSystemDocument(system).devices[0]?.id).toBe("group:roof");
    system.devices[0]!.id = "group:system:ungrouped";
    const projection = projectSystemDocument(system);
    expect(projection.workspace.groups[0]?.id).toBe("system:ungrouped:1");
  });
});
