// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { createEmptySystem } from "@/features/catalogue/systemDocument";
import { SystemLiveTelemetry } from "@/features/catalogue/systemLiveTelemetry";
import type { LiveStatus, LiveNodeSnapshot } from "@/features/catalogue/systemLiveTypes";
import type { SystemRuntime } from "@/features/catalogue/systemTypes";
import { buildNavigationIndex } from "@/features/explorer/navigationIndex";
import { readingActivity, type ReadingActivitySource } from "@/features/explorer/readingActivity";

const now = Date.parse("2026-10-13T12:00:00Z");
const time = (age = 0) => new Date(now - age).toISOString();
const document = { ...createEmptySystem(), connections: [{ id: "broker", label: "Broker", host: "localhost", protocol: "mqtt" as const, port: 1883, tls: false, transport: "tcp" as const }],
  streams: [{ id: "temperature", label: "Temperature", connection_id: "broker", topic: "room/temperature", value_type: "number" as const, category: "Environment" }] };
const index = buildNavigationIndex(document);
const node = index.nodes.get(index.objectKeys.get("temperature")![0]!)!;
const liveStatus: LiveStatus = { phase: "live", active: true, observing: false, message: "", dataSource: "broker", connections: [{ connection_id: "broker", state: "connected", message: null,
  received_messages: 1, fresh_count: 1, retained_count: 0, fresh_received_at: time(), rate_hz: 1 }] };

function recording(): ReadingActivitySource {
  const runtime: SystemRuntime = { mode: "collection", message: "", collection_revision: 7, collection: { status: "applied" },
    ingress: { revision: 7, status: "applied", sources: { broker: { state: "connected" } }, readings: { temperature: { fresh_received_at: time() } } },
    bindings: { temperature: { entity_id: "room", connection_id: "broker", telemetry_key: "temperature", accepted_topic: "telemetry/room/temperature", policy: { mode: "sample", interval_seconds: 3600 } } },
    latest_readings: { temperature: { value: 20, received_at: time(3_000_000), is_snapshot: false } } };
  return { runtime, telemetry: new SystemLiveTelemetry(), liveStreamIds: [] };
}

function preview(snapshot: Partial<LiveNodeSnapshot> = {}): ReadingActivitySource {
  const telemetry = new SystemLiveTelemetry();
  vi.spyOn(telemetry, "getSnapshot").mockReturnValue({ received: 1, lastSeen: now, receivedAt: now, latestValue: 21, value: 21, rate: 1, samples: [], retained: false,
    retainedCount: 0, decodeErrors: 0, isAggregate: false, ...snapshot });
  return { telemetry, liveStreamIds: ["temperature"] };
}

describe("topic activity", () => {
  it("shows fresh traffic independently of a long recording interval and old stored history", () => {
    expect(readingActivity(node, recording(), undefined, now)).toEqual({ receiving: true, label: "Receiving data (last 30 seconds)" });
  });

  it.each([0, 29_999, 30_000, 60_000, -60_000])("expires persistent activity at age %s milliseconds", age => {
    const source = recording();
    source.runtime!.ingress!.readings!.temperature!.fresh_received_at = time(age);
    expect(readingActivity(node, source, undefined, now).receiving).toBe(age >= 0 && age < 30_000);
  });

  it("waits for a fresh receipt even when retained stored data and a connected broker exist", () => {
    const source = recording();
    source.runtime!.ingress!.readings = {};
    source.runtime!.latest_readings!.temperature = { value: 20, received_at: time(), is_snapshot: true };
    expect(readingActivity(node, source, undefined, now)).toEqual({ receiving: false, label: "Listening, waiting for fresh data" });
    expect(readingActivity(node, preview({ received: 0, lastSeen: 0, retained: true }), liveStatus, now).receiving).toBe(false);
  });

  it.each(["off", "disconnected", "old-revision", "applying"])("does not present %s recording as receiving", state => {
    const source = recording();
    if (state === "off") source.runtime!.bindings!.temperature!.policy.mode = "off";
    if (state === "disconnected") source.runtime!.ingress!.sources!.broker!.state = "reconnecting";
    if (state === "old-revision") source.runtime!.ingress!.revision = 6;
    if (state === "applying") source.runtime!.collection!.status = "applying";
    expect(readingActivity(node, source, undefined, now)).toEqual({ receiving: false, label: "Not listening" });
  });

  it("uses fresh live receipts and labels simulated previews explicitly", () => {
    expect(readingActivity(node, preview(), liveStatus, now).receiving).toBe(true);
    expect(readingActivity(node, preview(), { ...liveStatus, dataSource: "simulated" }, now).label).toContain("simulated");
  });

  it.each(["stopped", "paused", "wrong-broker", "outside-scope"])("ignores cached preview receipts when %s", state => {
    const source = preview();
    const status = structuredClone(liveStatus);
    if (state === "stopped") status.active = false;
    if (state === "paused") status.phase = "paused";
    if (state === "wrong-broker") status.connections[0]!.connection_id = "other";
    if (state === "outside-scope") source.liveStreamIds = [];
    expect(readingActivity(node, source, status, now)).toEqual({ receiving: false, label: "Not listening" });
  });

  it("ages out a live receipt without requiring another network response", () => {
    expect(readingActivity(node, preview(), liveStatus, now + 30_000)).toEqual({ receiving: false, label: "Listening, waiting for fresh data" });
  });
});
