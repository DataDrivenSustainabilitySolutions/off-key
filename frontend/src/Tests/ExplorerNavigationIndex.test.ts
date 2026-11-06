// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  buildNavigationIndex,
  navigationRows,
  navigationTrail,
  searchNavigation,
  type NavigationIndex,
} from "@/domain/system/navigationIndex";
import { createEmptySystem } from "@/domain/system/systemDocument";
import type { SystemConnection, SystemDocument, SystemStream } from "@/types/system";
import { mqttConnection } from "./support/fixtures/system";

function connection(id = "broker", label = "Workshop broker"): SystemConnection {
  return mqttConnection({ id, label, host: "private-endpoint.invalid" });
}

function stream(id: string, topic: string, changes: Partial<SystemStream> = {}): SystemStream {
  return { id, label: id, topic, broker_id: "broker", value_type: "number", category: "Measurements", ...changes };
}

function fixture(changes: Partial<SystemDocument> = {}): SystemDocument {
  return { ...createEmptySystem("Test system"), brokers: [connection()], ...changes };
}

function object(index: NavigationIndex, id: string) {
  return index.nodes.get(index.objectKeys.get(id)![0]!)!;
}

describe("catalogue navigation index", () => {
  it("preserves generic devices and actual MQTT ancestry without touching the document", () => {
    const document = fixture({
      devices: [{ id: "room", label: "Room sensor", kind: "environment", broker_id: "broker" }],
      readings: [stream("temperature", "site/room/environment/temperature", { device_id: "room" })],
    });
    const original = structuredClone(document);
    const index = buildNavigationIndex(document);
    const broker = object(index, "broker");
    const room = object(index, "room");
    const reading = object(index, "temperature");
    expect(index.counts).toEqual({ connections: 1, devices: 1, topics: 1, readings: 1 });
    expect(navigationRows(index, index.rootKey).map((row) => row.node.key)).toEqual([broker.key]);
    expect(navigationRows(index, broker.key).map((row) => row.node.key)).toEqual([room.key]);
    expect(navigationRows(index, room.key)[0]).toMatchObject({
      label: "site/room/environment/temperature",
      node: { objectId: "temperature", entityKind: "stream", topic: "site/room/environment/temperature" },
    });
    expect(navigationRows(index, room.key)[0]!.trailKeys).toHaveLength(4);
    expect(navigationTrail(index, reading.key).map((node) => node.label)).toEqual([
      "Test system", "Workshop broker", "Room sensor", "site", "room", "environment", "temperature",
    ]);
    expect(index.nodes.get(index.rootKey)!.streamIds).toEqual(["temperature"]);
    expect(broker.streamIds).toEqual(["temperature"]);
    expect(room.streamIds).toEqual(["temperature"]);
    expect(document).toEqual(original);
  });

  it("keeps a topic's own reading visible beside child topic branches", () => {
    const index = buildNavigationIndex(fixture({ readings: [stream("state", "device"), stream("temperature", "device/temperature")] }));
    const broker = object(index, "broker");
    const rows = navigationRows(index, broker.key);
    expect(rows[0]!.label).toBe("device");
    expect(rows[0]!.node.streamIds).toEqual(["state"]);
    expect(rows[0]!.node.objectId).toBeUndefined();
    const children = navigationRows(index, rows[0]!.node.key);
    expect(children.map((row) => row.node.objectId)).toEqual(["state", "temperature"]);
    expect(object(index, "state").kind).toBe("reading");
    expect(object(index, "temperature").kind).toBe("topic");
    expect(broker.streamIds).toEqual(["state", "temperature"]);
  });

  it("exposes separate payload fields without duplicating an MQTT topic", () => {
    const index = buildNavigationIndex(fixture({ readings: [
      stream("Temperature", "room/environment", { payload_pointer: "/temperature" }),
      stream("Humidity", "room/environment", { payload_pointer: "/humidity" }),
    ] }));
    const endpoint = navigationRows(index, object(index, "broker").key)[0]!.node;
    expect(endpoint.topic).toBe("room/environment");
    expect(endpoint.streamIds).toEqual(["Temperature", "Humidity"]);
    expect(endpoint.entityKind).toBeUndefined();
    expect(navigationRows(index, endpoint.key).map((row) => row.label)).toEqual(["Humidity", "Temperature"]);
    expect(index.counts).toEqual({ connections: 1, devices: 0, topics: 1, readings: 2 });
    for (const id of ["Temperature", "Humidity"]) {
      expect(index.objectKeys.get(id)).toHaveLength(1);
      expect(object(index, id).kind).toBe("reading");
    }
    expect(searchNavigation(index, "/humidity").some((node) => node.objectId === "Humidity")).toBe(true);
  });

  it("preserves empty MQTT segments, trailing separators, Unicode, and dollar topics", () => {
    const topics = ["/a", "a//b", "a/", "$SYS/uptime", "λ/測定"];
    const index = buildNavigationIndex(fixture({ readings: topics.map((topic, position) => stream(`s-${position}`, topic)) }));
    for (let position = 0; position < topics.length; position += 1) {
      expect(object(index, `s-${position}`).topic).toBe(topics[position]);
    }
    expect(navigationTrail(index, object(index, "s-0").key).map((node) => node.label)).toContain("(empty level)");
    expect(navigationTrail(index, object(index, "s-1").key).map((node) => node.label)).toEqual([
      "Test system", "Workshop broker", "a", "(empty level)", "b",
    ]);
    expect(navigationTrail(index, object(index, "s-2").key).map((node) => node.label)).toEqual([
      "Test system", "Workshop broker", "a", "(empty level)", "s-2",
    ]);
    expect(searchNavigation(index, "$SYS/uptime").map((node) => node.objectId)).toContain("s-3");
    expect(searchNavigation(index, "測定").map((node) => node.objectId)).toContain("s-4");
    const emptyChain = buildNavigationIndex(fixture({ readings: [stream("empty", "//value/")] }));
    expect(navigationRows(emptyChain, object(emptyChain, "broker").key)[0]!.label).toBe("(empty level)/(empty level)/value/(empty level)");
  });

  it("uses collision-safe identities for brokers, entities, and exact topic paths", () => {
    const index = buildNavigationIndex(fixture({
      brokers: [connection("a:b", "Shared"), connection("a", "Shared")],
      devices: [
        { id: "c", label: "Same", kind: "sensor", broker_id: "a:b" },
        { id: "b:c", label: "Same", kind: "sensor", broker_id: "a" },
      ],
      readings: [
        stream('s:["quoted"]', "a//b", { broker_id: "a:b", device_id: "c" }),
        stream("s:quoted", "a/b", { broker_id: "a", device_id: "b:c" }),
      ],
    }));
    expect(index.objectKeys.size).toBe(6);
    expect(object(index, "c").key).not.toBe(object(index, "b:c").key);
    const selectable = Array.from(index.nodes.values()).filter((node) => node.entityKind === "stream");
    expect(selectable.map((node) => node.objectId).sort()).toEqual(['s:["quoted"]', "s:quoted"].sort());
    expect(new Set(selectable.map((node) => node.key)).size).toBe(2);
  });

  it("keeps device parents inside the actual broker context, including cross-broker bindings", () => {
    const document = fixture({
      brokers: [connection("broker", "Primary broker"), connection("secondary", "Secondary broker")],
      devices: [
        { id: "child", label: "Meter", kind: "sensor", parent_id: "parent", broker_id: "broker" },
        { id: "parent", label: "Cabinet", kind: "cabinet", broker_id: "broker" },
      ],
      readings: [
        stream("local", "cabinet/meter/power", { device_id: "child" }),
        stream("remote", "aux/power", { device_id: "child", broker_id: "secondary" }),
      ],
    });
    const index = buildNavigationIndex(document);
    expect(index.objectKeys.get("child")).toHaveLength(2);
    expect(navigationTrail(index, object(index, "local").key).map((node) => node.label)).toEqual([
      "Test system", "Primary broker", "Cabinet", "Meter", "cabinet", "meter", "power",
    ]);
    expect(navigationTrail(index, object(index, "remote").key).map((node) => node.label)).toEqual([
      "Test system", "Secondary broker", "Meter", "aux", "power",
    ]);
    expect(object(index, "parent").streamIds).toEqual(["local"]);
    expect(object(index, "secondary").streamIds).toEqual(["remote"]);
    expect(index.nodes.get(index.rootKey)!.streamIds).toEqual(["local", "remote"]);

    document.readings.push(stream("parent-remote", "cabinet/state", { device_id: "parent", broker_id: "secondary" }));
    const bothContexts = buildNavigationIndex(document);
    expect(navigationTrail(bothContexts, object(bothContexts, "remote").key).map((node) => node.label)).toContain("Cabinet");
    expect(navigationTrail(bothContexts, object(bothContexts, "remote").key)[1]!.objectId).toBe("secondary");
  });

  it("deduplicates topic counts across entity contexts without merging their readings", () => {
    const index = buildNavigationIndex(fixture({
      devices: ["a", "b"].map((id) => ({ id, label: id, kind: "sensor", broker_id: "broker" })),
      readings: [stream("a-value", "shared/payload", { device_id: "a" }), stream("b-value", "shared/payload", { device_id: "b" })],
    }));
    expect(index.counts.topics).toBe(1);
    expect(object(index, "a-value").key).not.toBe(object(index, "b-value").key);
    expect(index.objectKeys.get("a-value")).toHaveLength(1);
    expect(index.objectKeys.get("b-value")).toHaveLength(1);
    expect(object(index, "broker").streamIds.sort()).toEqual(["a-value", "b-value"]);
  });

  it("includes unassigned devices and preserves their explicit parent hierarchy", () => {
    const index = buildNavigationIndex(fixture({ devices: [
      { id: "child", label: "Child", kind: "sensor", parent_id: "parent" },
      { id: "parent", label: "Parent", kind: "room" },
    ] }));
    const rootRows = navigationRows(index, index.rootKey);
    expect(rootRows.map((row) => row.node.kind)).toEqual(["connection", "unassigned"]);
    expect(navigationTrail(index, object(index, "child").key).map((node) => node.label)).toEqual([
      "Test system", "Unassigned entities", "Parent", "Child",
    ]);
    expect(searchNavigation(index, "Parent Child").map((node) => node.objectId)).toContain("child");
  });

  it("searches closed branches by full path, aliases, and ancestors without indexing endpoints", () => {
    const index = buildNavigationIndex(fixture({
      devices: [{ id: "room", label: "North laboratory", kind: "sensor", broker_id: "broker" }],
      readings: [stream("reading", "hidden/deep/temperature", { label: "Air temperature", device_id: "room", unit: "°C" })],
    }));
    expect(searchNavigation(index, "north hidden/deep/temperature AIR").map((node) => node.objectId)).toEqual(["reading"]);
    expect(searchNavigation(index, "private-endpoint.invalid")).toEqual([]);
    expect(searchNavigation(index, "   ")).toEqual([]);
    expect(searchNavigation(index, "north", 0)).toEqual([]);
    expect(searchNavigation(index, "north", Number.NaN)).toEqual([]);
    expect(searchNavigation(index, "north", 0.9)).toEqual([]);
    expect(navigationRows(index, "missing")).toEqual([]);
    expect(navigationTrail(index, "missing")).toEqual([]);
  });

  it("keeps natural order and bounded search stable when catalogue input order changes", () => {
    const document = fixture({ readings: [stream("s-10", "metric10"), stream("s-2", "metric2"), stream("s-1", "metric1")] });
    const first = buildNavigationIndex(document);
    const second = buildNavigationIndex({ ...document, readings: [...document.readings].reverse() });
    expect(navigationRows(first, object(first, "broker").key).map((row) => row.label)).toEqual(["metric1", "metric2", "metric10"]);
    expect(searchNavigation(first, "metric", 2).map((node) => node.key)).toEqual(searchNavigation(second, "metric", 2).map((node) => node.key));
    expect(searchNavigation(first, "metric", 2).map((node) => node.objectId)).toEqual(["s-1", "s-2"]);
  });

  it("navigates deep topic chains iteratively without losing intermediate ancestry", () => {
    const segments = Array.from({ length: 600 }, (_, position) => `level${position}`);
    const index = buildNavigationIndex(fixture({ readings: [stream("deep", segments.join("/"))] }));
    const row = navigationRows(index, object(index, "broker").key)[0]!;
    expect(row.label).toBe(segments.join("/"));
    expect(row.trailKeys).toHaveLength(600);
    expect(row.node.objectId).toBe("deep");
    expect(navigationTrail(index, row.node.key)).toHaveLength(602);
    expect(searchNavigation(index, "level0/level1").some((node) => node.objectId === "deep")).toBe(true);
  });

  it("indexes thousands of siblings once and finds a late reading in a bounded result", () => {
    const index = buildNavigationIndex(fixture({ readings: Array.from({ length: 4000 }, (_, position) => stream(`signal-${position}`, `metrics/value${position}`)) }));
    const branch = navigationRows(index, object(index, "broker").key)[0]!.node;
    const rows = navigationRows(index, branch.key);
    expect(index.nodes.size).toBe(4003);
    expect(index.counts).toEqual({ connections: 1, devices: 0, topics: 4000, readings: 4000 });
    expect(rows).toHaveLength(4000);
    expect(rows[0]!.label).toBe("value0");
    expect(rows[10]!.label).toBe("value10");
    expect(rows[3999]!.node.objectId).toBe("signal-3999");
    expect(searchNavigation(index, "signal-3999", 1).map((node) => node.objectId)).toEqual(["signal-3999"]);
    expect(searchNavigation(index, "value")).toHaveLength(100);
    expect(object(index, "broker").streamIds).toHaveLength(4000);
  });

  it("ranks an entity whose serial number ends with the typed digits before readings that only contain them", () => {
    const serials = Array.from({ length: 40 }, (_, position) => `20251300000010002${String(position).padStart(2, "0")}`);
    const index = buildNavigationIndex(fixture({
      devices: serials.map((serial) => ({ id: serial, label: `Meter ${serial}`, kind: "sensor", broker_id: "broker" })),
      readings: serials.flatMap((serial) => ["temperature", "humidity"].map((key) => stream(`${serial}-${key}`, `meter/${serial}/${key}`, { device_id: serial }))),
    }));
    // The device earlier in the catalogue carries 219 only inside its readings' IDs.
    const decoy = buildNavigationIndex(fixture({
      devices: [{ id: "a", label: "Meter 1", kind: "sensor", broker_id: "broker" }, { id: "b", label: "Meter 2025130000001000219", kind: "sensor", broker_id: "broker" }],
      readings: [stream("port-2190", "meter/1/port2190", { device_id: "a" }), stream("b-power", "meter/b/power", { device_id: "b" })],
    }));
    expect(searchNavigation(index, "219")[0]!.label).toBe("Meter 2025130000001000219");
    // Its own topic folder and readings follow before anything from the other boxes.
    expect(searchNavigation(index, "219").slice(0, 4).every((node) => node.searchText.includes("2025130000001000219"))).toBe(true);
    expect(searchNavigation(index, "219").map((node) => node.objectId)).toEqual(expect.arrayContaining(["2025130000001000219-temperature", "2025130000001000219-humidity"]));
    expect(searchNavigation(decoy, "219")[0]!.objectId).toBe("b");
    expect(searchNavigation(decoy, "meter 219")[0]!.objectId).toBe("b");
    expect(searchNavigation(index, "Meter 2025130000001000207")[0]!.objectId).toBe("2025130000001000207");
  });

  it("orders matches by whole label, label start, number end, number start, anywhere, identifiers, then ancestry", () => {
    const labels = ["xx219xx", "Meter 219000", "219", "Box 0219", "219 rack", "Other"];
    const index = buildNavigationIndex(fixture({
      devices: labels.map((label, position) => ({ id: `d-${position}`, label, kind: "sensor", broker_id: "broker" })),
      readings: [stream("s-219", "plain/value", { label: "Plain", device_id: "d-5" }), stream("child", "plain/child", { label: "Child", device_id: "d-2" })],
    }));
    expect(searchNavigation(index, "219").map((node) => node.label)).toEqual([
      "219", "219 rack", "Box 0219", "Meter 219000", "xx219xx",
      // "value" matches by its reading ID; "child" and its folder only by their entity.
      "value", "child", "plain",
    ]);
  });

  it("keeps the best match of a broad query even when it comes last in a large catalogue", () => {
    const index = buildNavigationIndex(fixture({
      brokers: [connection(), connection("late", "Zulu broker")],
      readings: [
        ...Array.from({ length: 4000 }, (_, position) => stream(`signal-${position}`, `metrics/value${position}`)),
        stream("exact", "late/value", { broker_id: "late", label: "value" }),
      ],
    }));
    const results = searchNavigation(index, "value", 3);
    expect(results[0]!.objectId).toBe("exact");
    expect(results.map((node) => node.objectId)).toEqual(["exact", "signal-0", "signal-1"]);
  });

  it("keeps malformed parent cycles reachable rather than recursing indefinitely", () => {
    const index = buildNavigationIndex(fixture({ devices: [
      { id: "a", label: "A", kind: "sensor", broker_id: "broker", parent_id: "b" },
      { id: "b", label: "B", kind: "sensor", broker_id: "broker", parent_id: "a" },
    ] }));
    expect(index.nodes.size).toBe(4);
    expect(navigationTrail(index, object(index, "a").key)[0]!.key).toBe(index.rootKey);
    expect(navigationTrail(index, object(index, "b").key)[0]!.key).toBe(index.rootKey);
  });
});
