// @vitest-environment node
import { describe, expect, it } from "vitest";
import { createEmptySystem } from "@/domain/system/systemDocument";
import { SystemLiveTelemetry } from "@/domain/system/systemLiveTelemetry";
import type { SystemDocument, SystemRuntime } from "@/types/system";
import { buildNavigationIndex, navigationRows, navigationTrail, searchNavigation } from "@/domain/system/navigationIndex";
import { onlineNavigationIndex } from "@/domain/system/onlineNavigation";
import { mqttConnection } from "./support/fixtures/system";

const now = Date.parse("2026-10-16T12:00:00Z");
const connection = (id: string) => mqttConnection({ id, label: id, host: "localhost" });
const stream = (id: string, topic: string, connectionId = "broker", deviceId?: string) => ({
  id, label: id, topic, connection_id: connectionId, device_id: deviceId, value_type: "number" as const, category: "Test",
});
function activity(document: SystemDocument, receiving: string[]) {
  const telemetry = new SystemLiveTelemetry();
  const runtime: SystemRuntime = { mode: "collection", message: "", collection_revision: 3, collection: { status: "applied" },
    ingress: { revision: 3, status: "applied", sources: Object.fromEntries(document.connections.map(item => [item.id, { state: "connected" }])),
      readings: Object.fromEntries(receiving.map(id => [id, { fresh_received_at: new Date(now).toISOString() }])) },
    bindings: Object.fromEntries(document.streams.map(item => [item.id, { entity_id: "entity", connection_id: item.connection_id,
      telemetry_key: item.id, accepted_topic: item.topic, policy: { mode: "sample", interval_seconds: 3600 } }])) };
  return { telemetry, liveStreamIds: [], runtime };
}

describe("online catalogue navigation", () => {
  it("keeps complete paths to receiving leaves and removes inactive readings on parent topics", () => {
    const document: SystemDocument = { ...createEmptySystem(), connections: [connection("broker"), connection("offline")],
      devices: [{ id: "room", label: "Room", kind: "sensor", connection_id: "broker" }],
      streams: [stream("parent", "site", "broker", "room"), stream("active", "site/branch/active", "broker", "room"),
        stream("quiet", "site/branch/quiet", "broker", "room"), stream("disconnected", "elsewhere", "offline")] };
    const index = buildNavigationIndex(document);
    const original = structuredClone(index);
    const source = activity(document, ["active", "disconnected"]);
    source.runtime.ingress!.sources!.offline!.state = "reconnecting";
    const online = onlineNavigationIndex(index, source, source.telemetry.getStatus(), now);
    expect(online.counts).toEqual({ connections: 1, devices: 1, topics: 1, readings: 1 });
    expect([...online.objectKeys.keys()].sort()).toEqual(["active", "broker", "room"]);
    const activeKey = online.objectKeys.get("active")![0]!;
    expect(navigationTrail(online, activeKey).map(node => node.label)).toEqual([document.label, "broker", "Room", "site", "branch", "active"]);
    const roomKey = online.objectKeys.get("room")![0]!;
    expect(navigationRows(online, roomKey).map(row => row.label)).toEqual(["site/branch/active"]);
    expect(index).toEqual(original);
  });

  it("retains the online device context when another context for the same device is offline", () => {
    const document: SystemDocument = { ...createEmptySystem(), connections: [connection("first"), connection("second")],
      devices: [{ id: "shared", label: "Shared device", kind: "sensor", connection_id: "first" }],
      streams: [stream("quiet", "reading", "first", "shared"), stream("active", "reading", "second", "shared")] };
    const index = buildNavigationIndex(document);
    const source = activity(document, ["active"]);
    const online = onlineNavigationIndex(index, source, source.telemetry.getStatus(), now);
    expect(index.objectKeys.get("shared")).toHaveLength(2);
    expect(online.objectKeys.get("shared")).toHaveLength(1);
    expect(online.nodes.get(online.objectKeys.get("shared")![0]!)?.connectionId).toBe("second");
  });

  it("filters before the search result limit so offline matches cannot hide an online reading", () => {
    const document: SystemDocument = { ...createEmptySystem(), connections: [connection("broker")],
      streams: Array.from({ length: 120 }, (_, position) => stream(`signal-${position}`, `signal/${position}`)) };
    const index = buildNavigationIndex(document);
    const source = activity(document, ["signal-119"]);
    expect(searchNavigation(index, "signal").some(node => node.objectId === "signal-119")).toBe(false);
    const online = onlineNavigationIndex(index, source, source.telemetry.getStatus(), now);
    expect(searchNavigation(online, "signal")[0]?.objectId).toBe("signal-119");
  });

  it("expires paths with their last filled circle and keeps the root navigable", () => {
    const document: SystemDocument = { ...createEmptySystem(), connections: [connection("broker")], streams: [stream("active", "deep/path/reading")] };
    const index = buildNavigationIndex(document);
    const source = activity(document, ["active"]);
    const expired = onlineNavigationIndex(index, source, source.telemetry.getStatus(), now + 30_000);
    expect([...expired.nodes.keys()]).toEqual([index.rootKey]);
    expect(expired.counts.readings).toBe(0);
    expect(navigationRows(expired, index.rootKey)).toEqual([]);
    expect(onlineNavigationIndex(index, source, source.telemetry.getStatus(), now + 29_999).counts.readings).toBe(1);
  });
});
