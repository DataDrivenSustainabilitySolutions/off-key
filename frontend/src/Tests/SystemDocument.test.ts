// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  createEmptySystem,
  DEFAULT_GROUP_COLOR,
  newSystemEntity,
  upsertSystemEntity,
  importSystemDocument,
  parseSystemDocument,
  removeSystemEntity,
  renameSystemEntity,
  serializeSystemDocument,
  systemRemovalIds,
  validateSystemDocument,
} from "@/features/catalogue/systemDocument";
import type { SystemDocument } from "@/features/catalogue/systemTypes";

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

  it("accepts only the generic catalogue format", () => {
    expect(() => importSystemDocument(JSON.stringify({ provider: "ambibox", schema_version: 1, sources: [] }))).toThrow();
    expect(() => importSystemDocument(JSON.stringify({ format: "aberration-workspace", schema_version: 1 }))).toThrow();
  });


});

describe("catalogue entity edits", () => {
  const withSecondBroker = (): SystemDocument => {
    const system = systemFixture();
    system.connections.push({ ...system.connections[0]!, id: "connection:annex", label: "Annex broker" });
    system.groups.push({ id: "group:annex", label: "Annex", color: "#123456", member_ids: [] });
    return system;
  };

  it("creates new objects with the editor defaults", () => {
    const system = systemFixture();
    expect(newSystemEntity(system, "connection")).toMatchObject({ label: "New connection", port: 1883, transport: "tcp", tls: false });
    expect(newSystemEntity(system, "device")).toMatchObject({ kind: "device", connection_id: "connection:workshop" });
    expect(newSystemEntity(system, "stream")).toMatchObject({ connection_id: "connection:workshop", policy: { mode: "off", interval_seconds: 10 } });
    expect(newSystemEntity(system, "group")).toMatchObject({ label: "New collection", color: DEFAULT_GROUP_COLOR, member_ids: [] });
    expect(newSystemEntity(system, "stream").id).toMatch(/^stream:/);
  });

  it("replaces an existing object in place and appends a new one", () => {
    const system = withSecondBroker();
    const renamed = upsertSystemEntity(system, "connection", { ...system.connections[0]!, label: "Renamed" });
    expect(renamed.connections.map(item => [item.id, item.label])).toEqual([
      ["connection:workshop", "Renamed"], ["connection:annex", "Annex broker"],
    ]);
    const added = upsertSystemEntity(system, "device", { id: "device:new", label: "New", kind: "sensor" });
    expect(added.devices.map(item => item.id)).toEqual(["device:oven", "device:probe", "device:new"]);
  });

  it("moves a device's readings on its old broker along with it", () => {
    const system = withSecondBroker();
    system.devices[1]!.connection_id = "connection:workshop";
    const moved = upsertSystemEntity(system, "device", { ...system.devices[1]!, connection_id: "connection:annex" });
    expect(moved.streams[0]).toMatchObject({ id: "stream:temperature", connection_id: "connection:annex", topic: "workshop/oven/measurements" });
  });

  it("keeps explicit reading bindings when a device leaves its broker", () => {
    const system = systemFixture();
    const detached = { ...system.devices[1]! };
    delete detached.connection_id;
    const saved = upsertSystemEntity(system, "device", detached);
    expect(saved.devices[1]).not.toHaveProperty("connection_id");
    expect(saved.streams[0]?.connection_id).toBe("connection:workshop");
  });

  it("moves group members out of every other group", () => {
    const system = withSecondBroker();
    const saved = upsertSystemEntity(system, "group", { ...system.groups[1]!, member_ids: ["stream:temperature"] });
    expect(saved.groups.map(group => group.member_ids)).toEqual([
      ["connection:workshop", "device:oven", "device:probe"], ["stream:temperature"],
    ]);
  });
});
