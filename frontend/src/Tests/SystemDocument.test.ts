// @vitest-environment node
import fs from "node:fs";
import { describe, expect, it } from "vitest";
import {
  createEmptySystem,
  DEFAULT_GROUP_COLOR,
  newSystemEntity,
  upsertSystemEntity,
  parseSystemDocument,
  removeSystemEntity,
  renameSystemEntity,
  serializeSystemDocument,
  systemRemovalIds,
  validateSystemDocument,
} from "@/domain/system/systemDocument";
import type { SystemDocument } from "@/types/system";

const systemFixture = (): SystemDocument => ({
  ...createEmptySystem("Workshop"),
  brokers: [
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
      broker_id: "connection:workshop",
    },
    {
      id: "device:probe",
      label: "Probe",
      kind: "sensor",
      parent_id: "device:oven",
    },
  ],
  readings: [
    {
      id: "stream:temperature",
      label: "Temperature",
      broker_id: "connection:workshop",
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
    expect(serializeSystemDocument(system)).not.toMatch(
      /charger|password/,
    );
  });

  it("accepts nullable optional fields returned by the backend without storing null placeholders", () => {
    const system = systemFixture();
    const response = {
      ...system,
      brokers: system.brokers.map((entry) => ({
        ...entry,
        websocket_path: null,
      })),
      devices: system.devices.map((entry) => ({
        ...entry,
        parent_id: entry.parent_id ?? null,
        broker_id: entry.broker_id ?? null,
      })),
      readings: system.readings.map((entry) => ({
        ...entry,
        unit: null,
        payload_pointer: null,
        policy: null,
      })),
    };
    const parsed = validateSystemDocument(response);
    expect(parsed.brokers[0]).not.toHaveProperty("websocket_path");
    expect(parsed.readings[0]).not.toHaveProperty("policy");
  });

  it.each([
    (system: SystemDocument) => ({ ...system, password: "secret" }),
    (system: SystemDocument) => ({
      ...system,
      brokers: [{ ...system.brokers[0], password: "secret" }],
    }),
    (system: SystemDocument) => ({
      ...system,
      readings: [{ ...system.readings[0], broker_id: "missing" }],
    }),
    (system: SystemDocument) => ({
      ...system,
      readings: [{ ...system.readings[0], topic: "workshop/#" }],
    }),
    (system: SystemDocument) => ({
      ...system,
      readings: [{ ...system.readings[0], topic: "💧".repeat(129) }],
    }),
    (system: SystemDocument) => ({
      ...system,
      readings: [{ ...system.readings[0], payload_pointer: "/invalid~escape" }],
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
    expect(renamed.readings[0]).toEqual({
      ...before.readings[0],
      label: "Room temperature",
    });
    expect(before.readings[0]?.label).toBe("Temperature");
    expect(renamed.brokers).toEqual(before.brokers);
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
    expect(removed.readings).toEqual([]);
    expect(removed.groups[0]?.member_ids).toEqual(["connection:workshop"]);
    expect(removed.brokers).toEqual(before.brokers);
  });

  it("accepts only the generic catalogue format", () => {
    expect(() => parseSystemDocument(JSON.stringify({ provider: "legacy-provider", schema_version: 1, sources: [] }))).toThrow();
    expect(() => parseSystemDocument(JSON.stringify({ format: "aberration-workspace", schema_version: 1 }))).toThrow();
  });


});

describe("catalogue entity edits", () => {
  const withSecondBroker = (): SystemDocument => {
    const system = systemFixture();
    system.brokers.push({ ...system.brokers[0]!, id: "connection:annex", label: "Annex broker" });
    system.groups.push({ id: "group:annex", label: "Annex", color: "#123456", member_ids: [] });
    return system;
  };

  it("creates new objects with the editor defaults", () => {
    const system = systemFixture();
    expect(newSystemEntity(system, "connection")).toMatchObject({ label: "New connection", port: 1883, transport: "tcp", tls: false });
    expect(newSystemEntity(system, "device")).toMatchObject({ kind: "device", broker_id: "connection:workshop" });
    expect(newSystemEntity(system, "stream")).toMatchObject({ broker_id: "connection:workshop", policy: { mode: "off", interval_seconds: 10 } });
    expect(newSystemEntity(system, "group")).toMatchObject({ label: "New collection", color: DEFAULT_GROUP_COLOR, member_ids: [] });
    expect(newSystemEntity(system, "stream").id).toMatch(/^stream:/);
  });

  it("replaces an existing object in place and appends a new one", () => {
    const system = withSecondBroker();
    const renamed = upsertSystemEntity(system, "connection", { ...system.brokers[0]!, label: "Renamed" });
    expect(renamed.brokers.map(item => [item.id, item.label])).toEqual([
      ["connection:workshop", "Renamed"], ["connection:annex", "Annex broker"],
    ]);
    const added = upsertSystemEntity(system, "device", { id: "device:new", label: "New", kind: "sensor" });
    expect(added.devices.map(item => item.id)).toEqual(["device:oven", "device:probe", "device:new"]);
  });

  it("moves a device's readings on its old broker along with it", () => {
    const system = withSecondBroker();
    system.devices[1]!.broker_id = "connection:workshop";
    const moved = upsertSystemEntity(system, "device", { ...system.devices[1]!, broker_id: "connection:annex" });
    expect(moved.readings[0]).toMatchObject({ id: "stream:temperature", broker_id: "connection:annex", topic: "workshop/oven/measurements" });
  });

  it("keeps explicit reading bindings when a device leaves its broker", () => {
    const system = systemFixture();
    const detached = { ...system.devices[1]! };
    delete detached.broker_id;
    const saved = upsertSystemEntity(system, "device", detached);
    expect(saved.devices[1]).not.toHaveProperty("broker_id");
    expect(saved.readings[0]?.broker_id).toBe("connection:workshop");
  });

  it("moves group members out of every other group", () => {
    const system = withSecondBroker();
    const saved = upsertSystemEntity(system, "group", { ...system.groups[1]!, member_ids: ["stream:temperature"] });
    expect(saved.groups.map(group => group.member_ids)).toEqual([
      ["connection:workshop", "device:oven", "device:probe"], ["stream:temperature"],
    ]);
  });
});

type ConformanceCase = { name: string; valid: boolean; connection?: object; reading?: object; group?: object };
const conformance = JSON.parse(fs.readFileSync(
  new URL("../../../backend/tests/fixtures/system_document_conformance.json", import.meta.url), "utf8",
)) as { base: SystemDocument; default_group_color: string; cases: ConformanceCase[] };

describe("validator conformance with the backend model", () => {
  it.each(conformance.cases.map((item) => [item.name, item] as const))("%s", (_, item) => {
    const document = structuredClone(conformance.base);
    Object.assign(document.brokers[0]!, item.connection);
    if (item.reading) document.readings.push(item.reading as SystemDocument["readings"][number]);
    if (item.group) document.groups.push(item.group as SystemDocument["groups"][number]);
    if (item.valid) expect(() => validateSystemDocument(document)).not.toThrow();
    else expect(() => validateSystemDocument(document)).toThrow();
  });
  it("shows the colour the backend saves for a group without one", () => {
    expect(DEFAULT_GROUP_COLOR).toBe(conformance.default_group_color);
  });
});
