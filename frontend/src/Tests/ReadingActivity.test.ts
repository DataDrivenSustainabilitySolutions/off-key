// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { createEmptySystem } from "@/domain/system/systemDocument";
import { SystemLiveTelemetry } from "@/domain/system/systemLiveTelemetry";
import type { LiveStatus, LiveNodeSnapshot } from "@/types/system-live";
import type { SystemRuntime } from "@/types/system";
import { buildNavigationIndex } from "@/domain/system/navigationIndex";
import { activityWindow, readingActivity, type ReadingActivitySource } from "@/domain/system/readingActivity";
import { mqttConnection } from "./support/fixtures/system";

const now = Date.parse("2026-10-13T12:00:00Z");
const time = (age = 0) => new Date(now - age).toISOString();
const document = { ...createEmptySystem(), connections: [mqttConnection({ id: "broker", label: "Broker", host: "localhost" })],
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
    expect(readingActivity(node, recording(), undefined, now)).toEqual({ receiving: true, label: "Receiving data (last 2 minutes)" });
  });

  it.each([0, 119_999, 120_000, 180_000, -60_000])("expires persistent activity at age %s milliseconds", age => {
    const source = recording();
    source.runtime!.ingress!.readings!.temperature!.fresh_received_at = time(age);
    // A receipt from the future is browser clock skew, not stale data.
    expect(readingActivity(node, source, undefined, now).receiving).toBe(age < 120_000);
  });

  it("keeps a slow source receiving between its usual arrivals", () => {
    const source = recording();
    const reading = source.runtime!.ingress!.readings!.temperature!;
    reading.typical_interval_seconds = 180;
    reading.fresh_received_at = time(5 * 60_000);
    expect(readingActivity(node, source, undefined, now)).toEqual({ receiving: true, label: "Receiving data (last 9 minutes)" });
    reading.fresh_received_at = time(9 * 60_000);
    expect(readingActivity(node, source, undefined, now).receiving).toBe(false);
    expect(readingActivity(node, preview({ lastSeen: now - 5 * 60_000, typicalInterval: 180 }), liveStatus, now).receiving).toBe(true);
  });

  it.each([[null, 120_000], [1, 120_000], [60, 180_000], [86_400, 1_800_000]])(
    "bounds the activity window for a typical interval of %s seconds", (typical, window) => {
      expect(activityWindow(typical)).toBe(window);
    });

  it("waits for a fresh receipt even when retained stored data and a connected broker exist", () => {
    const source = recording();
    source.runtime!.ingress!.readings = {};
    source.runtime!.latest_readings!.temperature = { value: 20, received_at: time(), is_snapshot: true };
    expect(readingActivity(node, source, undefined, now)).toEqual({ receiving: false, label: "Listening, waiting for fresh data" });
    expect(readingActivity(node, preview({ received: 0, lastSeen: 0, retained: true }), liveStatus, now).receiving).toBe(false);
  });

  it("keeps fast readings receiving through a short broker reconnect", () => {
    const source = recording();
    source.runtime!.ingress!.sources!.broker!.state = "reconnecting";
    source.runtime!.ingress!.readings!.temperature = { fresh_received_at: time(60_000), typical_interval_seconds: 1 };
    expect(readingActivity(node, source, undefined, now)).toEqual({ receiving: true, label: "Broker reconnecting, received data (last 2 minutes)" });
    source.runtime!.ingress!.readings!.temperature!.fresh_received_at = time(120_000);
    expect(readingActivity(node, source, undefined, now)).toEqual({ receiving: false, label: "Not listening" });
    const status = structuredClone(liveStatus);
    status.phase = "reconnecting";
    status.connections[0]!.state = "reconnecting";
    expect(readingActivity(node, preview({ lastSeen: now - 60_000, typicalInterval: 1 }), status, now).receiving).toBe(true);
  });

  it.each(["off", "disconnected", "old-revision", "applying"])("does not present %s recording as receiving", state => {
    const source = recording();
    if (state === "off") source.runtime!.bindings!.temperature!.policy.mode = "off";
    if (state === "disconnected") source.runtime!.ingress!.sources!.broker!.state = "error";
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
    expect(readingActivity(node, preview(), liveStatus, now + 120_000)).toEqual({ receiving: false, label: "Listening, waiting for fresh data" });
  });
});
