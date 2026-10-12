import { describe, expect, it } from "vitest";
import {
  createEmptySystem,
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
