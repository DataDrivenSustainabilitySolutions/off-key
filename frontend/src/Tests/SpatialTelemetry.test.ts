import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DemoTelemetry, SAMPLE_LIMIT } from "@/features/spatial/telemetry";
import {
  HSL_TOPIC,
  HslTelemetry,
  parseHslPayload,
} from "@/features/spatial/live-source";
import type {
  SpatialNode,
  TelemetryMessage,
  Topology,
} from "@/features/spatial/types";

const mqttMock = vi.hoisted(() => {
  type Handler = (...args: unknown[]) => void;
  const handlers = new Map<string, Handler[]>();
  const client = {
    on: vi.fn((event: string, callback: Handler) => {
      handlers.set(event, [...(handlers.get(event) ?? []), callback]);
      return client;
    }),
    subscribe: vi.fn(),
    removeAllListeners: vi.fn(() => {
      handlers.clear();
    }),
    end: vi.fn(),
  };
  return { handlers, client, connect: vi.fn(() => client) };
});
// MQTT.js's browser ESM entry deliberately exposes only a default export.
vi.mock("mqtt", () => ({ default: { connect: mqttMock.connect } }));

const now = Date.parse("2026-10-06T12:00:00Z");
const nodes: SpatialNode[] = [
  {
    id: "broker",
    label: "Broker",
    kind: "broker",
    groupId: "environment",
    position: { x: 0, z: 0 },
    locked: false,
    unit: "msg/s",
    metric: "Arrivals",
    baseRate: 0,
  },
  {
    id: "temperature",
    label: "Temperature",
    kind: "sensor",
    brokerId: "broker",
    groupId: "environment",
    position: { x: 4, z: 0 },
    locked: false,
    unit: "°C",
    metric: "Temperature",
    baseRate: 1,
  },
];

function payload(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    VP: {
      oper: 40,
      veh: 105,
      spd: 10,
      tst: new Date(now).toISOString(),
      desi: "7",
      ...overrides,
    },
  });
}

function emit(event: string, ...args: unknown[]): void {
  for (const callback of [...(mqttMock.handlers.get(event) ?? [])])
    callback(...args);
}

async function liveSource(): Promise<{
  source: HslTelemetry;
  topologies: Topology[];
  events: TelemetryMessage[];
}> {
  const topologies: Topology[] = [];
  const events: TelemetryMessage[] = [];
  const source = new HslTelemetry({
    onTopology: (topology) => topologies.push(topology),
    onStatus: () => {},
  });
  source.subscribe((event) => events.push(event));
  source.start();
  await vi.dynamicImportSettled();
  emit("connect");
  return { source, topologies, events };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(now);
  vi.clearAllMocks();
  mqttMock.handlers.clear();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("spatial simulated telemetry", () => {
  it("bounds history and counts observed arrivals separately from synthetic seed history", () => {
    const source = new DemoTelemetry(nodes);
    const received: TelemetryMessage[] = [];
    source.subscribe((message) => received.push(message));
    expect(source.getSnapshot("temperature")?.samples).toHaveLength(120);
    expect(source.getSnapshot("temperature")?.received).toBe(0);
    source.setRate("temperature", 10);
    source.start();
    vi.advanceTimersByTime(50_000);
    const snapshot = source.getSnapshot("temperature")!;
    expect(snapshot.samples).toHaveLength(SAMPLE_LIMIT);
    expect(snapshot.received).toBeGreaterThan(SAMPLE_LIMIT);
    expect(snapshot.samples[0]!.timestamp).toBeGreaterThan(now);
    expect(source.getSnapshot("broker")?.received).toBe(snapshot.received);
    expect(received.every((message) => message.nodeId === "temperature")).toBe(
      true,
    );
    source.dispose();
  });

  it("pauses without replaying a backlog, and a zero cadence remains quiet", () => {
    const source = new DemoTelemetry(nodes);
    const listener = vi.fn();
    source.subscribe(listener);
    source.start();
    vi.advanceTimersByTime(2_000);
    source.setPaused(true);
    const beforePause = listener.mock.calls.length;
    vi.advanceTimersByTime(120_000);
    expect(listener).toHaveBeenCalledTimes(beforePause);
    source.setPaused(false);
    vi.advanceTimersByTime(100);
    expect(listener).toHaveBeenCalledTimes(beforePause);
    vi.advanceTimersByTime(2_000);
    expect(listener.mock.calls.length - beforePause).toBeLessThanOrEqual(3);
    source.setRate("temperature", 0);
    const beforeQuiet = listener.mock.calls.length;
    vi.advanceTimersByTime(30_000);
    expect(listener).toHaveBeenCalledTimes(beforeQuiet);
    expect(source.getSnapshot("temperature")?.rate).toBe(0);
    source.dispose();
  });

  it("prunes removed sources and stops all callbacks after disposal", () => {
    const source = new DemoTelemetry(nodes);
    const listener = vi.fn();
    source.subscribe(listener);
    source.start();
    source.setNodes(nodes.slice(0, 1));
    expect(source.getSnapshot("temperature")).toBeUndefined();
    vi.advanceTimersByTime(5_000);
    expect(listener).not.toHaveBeenCalled();
    source.setNodes(nodes);
    source.dispose();
    source.setPaused(false);
    vi.advanceTimersByTime(5_000);
    expect(listener).not.toHaveBeenCalled();
  });

  it("supports StrictMode start, dispose, and start without replaying obsolete subscriptions", () => {
    const source = new DemoTelemetry(nodes);
    const oldListener = vi.fn();
    const newListener = vi.fn();
    source.subscribe(oldListener);
    source.start();
    source.dispose();
    // React may install a child's subscription before restarting its parent effect.
    source.subscribe(newListener);
    source.start();
    vi.advanceTimersByTime(3_000);
    expect(oldListener).not.toHaveBeenCalled();
    expect(newListener).toHaveBeenCalled();
    source.dispose();
  });
});

describe("HSL public telemetry payload validation", () => {
  it("converts documented m/s speed to km/h and uses the vehicle timestamp", () => {
    expect(parseHslPayload(payload(), now + 1_000)).toEqual({
      id: "hsl:40:105",
      label: "Tram 105 · line 7",
      timestamp: now,
      value: 36,
    });
    expect(
      parseHslPayload(payload({ tst: "invalid" }), now + 1_000)?.timestamp,
    ).toBe(now + 1_000);
  });

  it.each([
    "malformed",
    "null",
    "[]",
    '{"VP": null}',
    '{"VP": {}}',
    payload({ spd: null }),
    payload({ spd: "10" }),
    payload({ spd: -1 }),
    payload({ spd: 200 }),
    payload({ oper: "40" }),
    payload({ veh: -4 }),
    payload({ veh: 1.5 }),
  ])(
    "rejects a malformed measurement without fabricating data: %s",
    (input) => {
      expect(parseHslPayload(input, now)).toBeUndefined();
    },
  );
});

describe("HSL public feed lifecycle", () => {
  it("connects through the default-only browser module and bounds tracked topology", async () => {
    const { source, topologies } = await liveSource();
    expect(mqttMock.connect).toHaveBeenCalledWith(
      "wss://mqtt.hsl.fi:443/",
      expect.objectContaining({
        reconnectPeriod: 30_000,
        connectTimeout: 10_000,
      }),
    );
    expect(mqttMock.client.subscribe).toHaveBeenCalledWith(
      HSL_TOPIC,
      { qos: 0 },
      expect.any(Function),
    );
    for (let veh = 1; veh <= 100; veh++) {
      emit(
        "message",
        "/hfp/v2/journey/ongoing/vp/tram/0040/00105/rest",
        new TextEncoder().encode(payload({ veh })),
        { retain: false },
      );
    }
    expect(topologies).toHaveLength(1);
    vi.advanceTimersByTime(1_000);
    expect(topologies).toHaveLength(2);
    expect(topologies[1]?.nodes).toHaveLength(25);
    expect(source.getSnapshot("hsl:40:25")).toBeUndefined();
    expect(source.getSnapshot("hsl:broker")?.received).toBe(24);
    source.dispose();
  });

  it("never pulses retained history and ignores stale handlers after disposal", async () => {
    const { source, events } = await liveSource();
    const topic = "/hfp/v2/journey/ongoing/vp/tram/0040/00105/rest";
    const bytes = new TextEncoder().encode(payload());
    emit("message", topic, bytes, { retain: true });
    expect(source.getSnapshot("hsl:40:105")?.samples).toHaveLength(1);
    expect(source.getSnapshot("hsl:40:105")?.received).toBe(0);
    expect(events).toHaveLength(0);
    emit("message", topic, bytes, { retain: false });
    expect(events).toHaveLength(1);
    const staleHandler = mqttMock.handlers.get("message")![0]!;
    source.dispose();
    staleHandler(topic, bytes, { retain: false });
    vi.advanceTimersByTime(2_000);
    expect(events).toHaveLength(1);
    expect(mqttMock.client.end).toHaveBeenCalledWith(true);
    expect([...mqttMock.handlers.keys()]).toEqual(["error"]);
    expect(() =>
      emit("error", new Error("Late CONNACK timeout")),
    ).not.toThrow();
  });

  it("closes the live socket on pause and rejects paused callbacks", async () => {
    const { source, events } = await liveSource();
    const staleHandler = mqttMock.handlers.get("message")![0]!;
    source.setPaused(true);
    staleHandler(
      "/hfp/v2/journey/ongoing/vp/tram/0040/00105/rest",
      new TextEncoder().encode(payload()),
      { retain: false },
    );
    expect(events).toHaveLength(0);
    expect(mqttMock.client.end).toHaveBeenCalledWith(true);
    source.dispose();
  });

  it("guards an obsolete asynchronous connect during StrictMode restart", async () => {
    const statuses: string[] = [];
    const source = new HslTelemetry({
      onTopology: () => {},
      onStatus: (status) => statuses.push(status),
    });
    source.start();
    source.dispose();
    const listener = vi.fn();
    source.subscribe(listener);
    source.start();
    await vi.dynamicImportSettled();
    await vi.waitFor(() =>
      expect(
        mqttMock.connect.mock.calls,
        JSON.stringify(statuses),
      ).toHaveLength(1),
    );
    emit(
      "message",
      "/hfp/v2/journey/ongoing/vp/tram/0040/00105/rest",
      new TextEncoder().encode(payload()),
      { retain: false },
    );
    expect(listener).toHaveBeenCalledTimes(1);
    source.dispose();
  });

  it("reports a failed module or connection setup without leaving subscriptions running", async () => {
    mqttMock.connect.mockImplementationOnce(() => {
      throw new Error("MQTT API unavailable");
    });
    const statuses: string[] = [];
    const onTopology = vi.fn();
    const listener = vi.fn();
    const source = new HslTelemetry({
      onTopology,
      onStatus: (status) => statuses.push(status),
    });
    source.subscribe(listener);
    source.start();
    await vi.dynamicImportSettled();
    expect(statuses[statuses.length - 1]).toBe(
      "Live source unavailable · simulation remains available",
    );
    expect(mqttMock.client.subscribe).not.toHaveBeenCalled();
    source.dispose();
    const topologyCalls = onTopology.mock.calls.length;
    vi.advanceTimersByTime(30_000);
    expect(onTopology).toHaveBeenCalledTimes(topologyCalls);
    expect(listener).not.toHaveBeenCalled();
  });
});
