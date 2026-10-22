import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError } from "@/lib/api-client";
import { createEmptySystem } from "@/features/catalogue/systemDocument";
import {
  LIVE_HISTORY_LIMIT,
  SystemLiveTelemetry,
} from "@/features/catalogue/systemLiveTelemetry";
import type {
  LiveBatch,
  LiveLease,
  LiveStream,
} from "@/features/catalogue/systemLiveTypes";
import type { SystemDocument } from "@/features/catalogue/systemTypes";

const NOW = Date.parse("2026-10-07T12:00:00Z");
const iso = (offset = 0) => new Date(NOW + offset).toISOString();
const document: SystemDocument = {
  ...createEmptySystem(),
  connections: [
    {
      id: "broker",
      label: "Broker",
      protocol: "mqtt",
      host: "broker.test",
      port: 1883,
      tls: false,
      transport: "tcp",
    },
  ],
  devices: [
    { id: "device", label: "Device", kind: "sensor", connection_id: "broker" },
  ],
  streams: ["temperature", "switch", "label"].map((id) => ({
    id,
    label: id,
    connection_id: "broker",
    device_id: "device",
    topic: `site/${id}`,
    value_type:
      id === "switch" ? "boolean" : id === "label" ? "text" : "number",
    category: "Other",
  })),
};
const record = (overrides: Partial<LiveStream> = {}): LiveStream => ({
  stream_id: "temperature",
  value: 20,
  received_at: iso(),
  is_retained: false,
  received_count: 1,
  fresh_count: 1,
  retained_count: 0,
  decode_errors: 0,
  fresh_received_at: iso(),
  rate_hz: 1,
  sequence: 1,
  ...overrides,
});
const batch = (overrides: Partial<LiveBatch> = {}): LiveBatch => ({
  mode: "live",
  revision: 7,
  sequence: 1,
  reset: false,
  connections: [
    {
      connection_id: "broker",
      state: "connected",
      message: "Connected",
      received_messages: 1,
      fresh_count: 1,
      retained_count: 0,
      fresh_received_at: iso(),
      rate_hz: 1,
    },
  ],
  streams: [record()],
  samples: [
    {
      sequence: 1,
      stream_id: "temperature",
      value: 20,
      received_at: iso(),
      is_retained: false,
    },
  ],
  limits: {
    max_samples: LIVE_HISTORY_LIMIT,
    history_seconds: 7200,
    sample_interval_seconds: 1,
    lease_seconds: 45,
  },
  ...overrides,
});
const lease = (telemetry = batch()): LiveLease => ({
  lease_id: "lease",
  expires_in_seconds: 45,
  telemetry,
});
function harness(canStart = true) {
  const api = {
    create: vi.fn().mockResolvedValue(lease()),
    renew: vi.fn().mockResolvedValue(lease()),
    read: vi.fn().mockResolvedValue(batch()),
    release: vi.fn().mockResolvedValue(undefined),
  };
  const source = new SystemLiveTelemetry(api);
  source.configure(document, 7, "user1", canStart);
  return { source, api };
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

describe("generic live telemetry receipts", () => {
  it("preserves visited readings across scope resets without duplicate replay or sequence collisions", () => {
    const { source } = harness();
    source.accept(batch(), false);
    source.accept(batch({ sequence: 50, streams: [record({ sequence: 50, value: 21 })],
      samples: [{ sequence: 50, stream_id: "temperature", received_at: iso(1000), value: 21, is_retained: false }] }), true);
    source.accept(batch({ reset: true, sequence: 51, streams: [record({ stream_id: "switch", value: true, sequence: 51 })],
      samples: [{ sequence: 51, stream_id: "switch", received_at: iso(1500), value: true, is_retained: false }] }), true);
    expect(source.getSnapshot("temperature")?.samples).toHaveLength(2);
    source.accept(batch({ reset: true, sequence: 1, streams: [record({ sequence: 1, value: 21 })],
      samples: [{ sequence: 1, stream_id: "temperature", received_at: iso(1000), value: 21, is_retained: false }] }), false);
    source.accept(batch({ sequence: 2, streams: [record({ sequence: 2, value: 22 })],
      samples: [{ sequence: 2, stream_id: "temperature", received_at: iso(2000), value: 22, is_retained: false }] }), true);
    expect(source.getSnapshot("temperature")?.samples).toEqual([
      { timestamp: NOW, value: 20 }, { timestamp: NOW + 1000, value: 21 }, { timestamp: NOW + 2000, value: 22 },
    ]);
    source.configure(document, 7, "another-user", true);
    expect(source.getSnapshot("temperature")).toBeUndefined();
  });
  it("labels operator-marked simulation without changing received values", async () => {
    const telemetry = batch({ data_source: "simulated" });
    const { source, api } = harness();
    api.create.mockResolvedValue(lease(telemetry));
    api.read.mockResolvedValue(telemetry);
    await source.start();
    expect(source.getStatus().dataSource).toBe("simulated");
    expect(source.getStatus().message).toBe("Simulated data · memory only");
    expect(source.getSnapshot("temperature")?.latestValue).toBe(20);
    source.stop();
  });
  it("counts coalesced arrivals while limiting visual pulses and deduplicating replay", () => {
    const { source } = harness();
    const pulse = vi.fn();
    source.subscribe(pulse);
    source.accept(batch({ reset: true }), true);
    expect(pulse).not.toHaveBeenCalled();
    const update = batch({
      sequence: 100,
      streams: [
        record({
          sequence: 100,
          fresh_count: 100,
          received_count: 100,
          rate_hz: 10,
        }),
      ],
      samples: [
        {
          sequence: 100,
          stream_id: "temperature",
          received_at: iso(1000),
          value: 22,
          is_retained: false,
        },
      ],
    });
    source.accept(update, true);
    expect(source.getSnapshot("temperature")).toMatchObject({
      received: 100,
      rate: 10,
    });
    expect(pulse).toHaveBeenCalledTimes(1);
    source.accept(update, true);
    expect(pulse).toHaveBeenCalledTimes(1);
    expect(source.getSnapshot("temperature")?.samples).toHaveLength(2);
    source.stop();
  });
  it("shows retained values without fresh receipt counts, time or pulses", () => {
    const { source } = harness();
    const pulse = vi.fn();
    source.subscribe(pulse);
    source.accept(batch({ reset: true }), false);
    source.accept(
      batch({
        sequence: 2,
        streams: [
          record({
            sequence: 2,
            is_retained: true,
            retained_count: 1,
            fresh_count: 0,
            fresh_received_at: null,
          }),
        ],
        samples: [
          {
            sequence: 2,
            stream_id: "temperature",
            received_at: iso(),
            value: 19,
            is_retained: true,
          },
        ],
      }),
      true,
    );
    expect(source.getSnapshot("temperature")).toMatchObject({
      latestValue: 20,
      received: 0,
      lastSeen: 0,
      retained: true,
      retainedCount: 1,
    });
    expect(pulse).not.toHaveBeenCalled();
    source.stop();
  });
  it("plots boolean state, preserves text and aggregates device stream counts", () => {
    const { source } = harness();
    source.accept(
      batch({
        streams: [
          record({ stream_id: "switch", value: true, fresh_count: 3 }),
          record({ stream_id: "label", value: "Kitchen", fresh_count: 5 }),
        ],
        samples: [
          {
            sequence: 1,
            stream_id: "switch",
            value: true,
            received_at: iso(),
            is_retained: false,
          },
          {
            sequence: 2,
            stream_id: "label",
            value: "Kitchen",
            received_at: iso(),
            is_retained: false,
          },
        ],
      }),
      false,
    );
    expect(source.getSnapshot("switch")?.samples).toEqual([
      { timestamp: NOW, value: 1 },
    ]);
    expect(source.getSnapshot("label")).toMatchObject({
      latestValue: "Kitchen",
      samples: [],
    });
    expect(source.getSnapshot("device")).toMatchObject({
      received: 8,
      rate: 2,
      isAggregate: true,
    });
    source.stop();
  });
  it("bounds history globally and retains actual receipt timestamps", () => {
    const { source } = harness();
    const ids = ["temperature", "switch", "label"];
    const samples = Array.from(
      { length: LIVE_HISTORY_LIMIT + 10 },
      (_, index) => ({
        sequence: index + 1,
        stream_id: ids[index % 3]!,
        received_at: iso((Math.floor(index / 3) - 3000) * 1000),
        value: index,
        is_retained: false,
      }),
    );
    source.accept(
      batch({
        sequence: samples.length,
        samples,
        streams: ids.map((id) => record({ stream_id: id })),
      }),
      false,
    );
    const values = source.getSnapshot("temperature")!.samples;
    expect(
      ids.reduce(
        (count, id) => count + source.getSnapshot(id)!.samples.length,
        0,
      ),
    ).toBe(LIVE_HISTORY_LIMIT);
    expect(values[0]).toEqual({ timestamp: NOW - 2996000, value: 12 });
    source.stop();
  });
  it("ignores unknown stream identities and stale replay pulses", () => {
    const { source } = harness();
    const pulse = vi.fn();
    source.subscribe(pulse);
    source.accept(batch({ reset: true }), true);
    source.accept(
      batch({
        sequence: 2,
        streams: [
          record({ stream_id: "unknown", fresh_count: 50 }),
          record({
            sequence: 2,
            fresh_count: 2,
            fresh_received_at: iso(-6000),
          }),
        ],
        samples: [
          {
            sequence: 2,
            stream_id: "unknown",
            received_at: iso(),
            value: 3,
            is_retained: false,
          },
        ],
      }),
      true,
    );
    expect(source.getSnapshot("unknown")).toBeUndefined();
    expect(pulse).not.toHaveBeenCalled();
    source.stop();
  });
  it("clears readings after a revised configuration or changed account", () => {
    const { source } = harness();
    source.accept(batch(), false);
    source.configure({ ...document, label: "New revision" }, 8, "user1", true);
    expect(source.getSnapshot("temperature")).toBeUndefined();
    expect(source.getStatus().phase).toBe("idle");
    source.stop();
  });
});

describe("live configuration and sampling", () => {
  it("keeps active readings when a refresh returns the same saved revision", async () => {
    const { source, api } = harness();
    await source.start();
    source.configure({ ...document }, 7, "user1", true);
    expect(source.getSnapshot("temperature")?.received).toBe(1);
    expect(api.release).not.toHaveBeenCalled();
    source.stop();
  });
  it("updates a decayed rate without fabricating an arrival or sample", () => {
    const { source } = harness();
    const pulse = vi.fn();
    source.subscribe(pulse);
    source.accept(batch(), false);
    source.accept(
      batch({
        sequence: 2,
        streams: [record({ sequence: 2, rate_hz: 0 })],
        samples: [],
      }),
      true,
    );
    expect(source.getSnapshot("temperature")?.rate).toBe(0);
    expect(source.getSnapshot("temperature")?.samples).toHaveLength(1);
    expect(pulse).not.toHaveBeenCalled();
    source.stop();
  });
  it("replaces a coalesced point in the same second instead of duplicating it", () => {
    const { source } = harness();
    source.accept(batch(), false);
    source.accept(
      batch({
        sequence: 2,
        samples: [
          {
            sequence: 2,
            stream_id: "temperature",
            received_at: iso(500),
            value: 25,
            is_retained: false,
          },
        ],
      }),
      false,
    );
    expect(source.getSnapshot("temperature")?.samples).toEqual([
      { timestamp: NOW + 500, value: 25 },
    ]);
    source.stop();
  });
  it("caps sampled pulses and reserves the inspected stream while preserving every count", () => {
    const { source } = harness();
    const pulse = vi.fn();
    source.subscribe(pulse);
    const streams = Array.from({ length: 100 }, (_, index) => ({
      ...document.streams[0]!,
      id: `stream-${index}`,
    }));
    source.configure({ ...document, streams }, 7, "user1", true);
    source.setPriority("stream-99");
    source.accept(
      batch({
        sequence: 0,
        reset: true,
        samples: [],
        streams: streams.map((stream) =>
          record({ stream_id: stream.id, fresh_count: 0, sequence: 0 }),
        ),
      }),
      false,
    );
    source.accept(
      batch({
        sequence: 100,
        samples: [],
        streams: streams.map((stream, index) =>
          record({
            stream_id: stream.id,
            fresh_count: 100,
            sequence: index + 1,
          }),
        ),
      }),
      true,
    );
    expect(pulse).toHaveBeenCalledTimes(60);
    expect(pulse.mock.calls[0]?.[0].nodeId).toBe("stream-99");
    expect(source.getSnapshot("stream-99")?.received).toBe(100);
    source.stop();
  });
});

describe("scene telemetry reads", () => {
  it("does not scan or materialize history when rendering many objects across frames", () => {
    const { source } = harness();
    source.accept(
      batch({
        streams: document.streams.map((stream) =>
          record({ stream_id: stream.id }),
        ),
      }),
      false,
    );
    const history = (
      source as unknown as { history: { samples: (id: string) => unknown } }
    ).history;
    const samples = vi.spyOn(history, "samples");
    const device = source.getSnapshot("device");
    const stream = source.getSnapshot("temperature");
    const broker = source.getSnapshot("broker");
    for (let frame = 0; frame < 1000; frame++) {
      for (const id of ["temperature", "switch", "label", "device", "broker"]) {
        const record = source.getSnapshot(id)!;
        expect(record.received).toBeGreaterThan(0);
        expect(record.rate).toBeGreaterThan(0);
      }
      expect(source.getSnapshot("device")).toBe(device);
      expect(source.getSnapshot("temperature")).toBe(stream);
      expect(source.getSnapshot("broker")).toBe(broker);
    }
    expect(samples).not.toHaveBeenCalled();
    expect(stream?.samples).toHaveLength(1);
    expect(samples).toHaveBeenCalledTimes(1);
    source.stop();
  });
  it("invalidates cached aggregates only when a batch changes readings", () => {
    const { source } = harness();
    source.accept(batch(), false);
    const device = source.getSnapshot("device");
    source.accept(
      batch({
        sequence: 2,
        streams: [record({ received_count: 3, fresh_count: 3, sequence: 2 })],
        samples: [],
      }),
      false,
    );
    expect(source.getSnapshot("device")).not.toBe(device);
    expect(source.getSnapshot("device")?.received).toBe(3);
    source.stop();
  });
});

describe("generic live preview lease lifecycle", () => {
  it("waits for a focused selection without timing out and renews its exact scope", async () => {
    const { source, api } = harness();
    const empty = batch({ connections: [], streams: [], samples: [] });
    api.create.mockResolvedValue(lease(empty));
    api.read.mockResolvedValue(empty);
    api.renew.mockResolvedValue(lease(empty));
    source.setScope([]);
    await source.start();
    expect(api.create).toHaveBeenCalledWith(7, []);
    expect(source.getStatus().message).toBe("Select a reading to view live data.");
    await vi.advanceTimersByTimeAsync(30000);
    expect(source.getStatus().phase).toBe("waiting");
    expect(source.getStatus().active).toBe(true);
    expect(api.release).not.toHaveBeenCalled();
    api.renew.mockResolvedValue(lease());
    api.read.mockResolvedValue(batch());
    source.setScope(["temperature", "temperature"]);
    await vi.advanceTimersByTimeAsync(1250);
    expect(api.renew).toHaveBeenLastCalledWith("lease", expect.any(AbortSignal), ["temperature"]);
    expect(source.getStatus().phase).toBe("live");
    source.stop();
  });
  it("releases an all-failed attempt and preserves broker diagnostics for retry", async () => {
    const { source, api } = harness();
    const failure = batch({
      connections: [{
        ...batch().connections[0]!,
        state: "error",
        message: "Check network or VPN access, then retry.",
      }],
    });
    api.create.mockResolvedValue(lease(failure));
    await source.start();
    expect(source.getStatus()).toMatchObject({
      phase: "error",
      active: false,
      connections: failure.connections,
    });
    expect(api.release).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(60000);
    source.resume();
    expect(api.read).not.toHaveBeenCalled();
    expect(api.renew).not.toHaveBeenCalled();
    expect(api.create).toHaveBeenCalledTimes(1);
    api.create.mockResolvedValue(lease());
    await source.start();
    expect(source.getStatus()).toMatchObject({ phase: "live", active: true });
    source.stop();
  });
  it("bounds connecting even if the service never marks a broker failed", async () => {
    const { source, api } = harness();
    const pending = batch({
      connections: [{ ...batch().connections[0]!, state: "reconnecting" }],
      streams: [],
      samples: [],
    });
    api.create.mockResolvedValue(lease(pending));
    api.read.mockResolvedValue(pending);
    await source.start();
    await vi.advanceTimersByTimeAsync(19999);
    expect(source.getStatus().active).toBe(true);
    await vi.advanceTimersByTimeAsync(1);
    expect(source.getStatus()).toMatchObject({ phase: "error", active: false });
    expect(source.getStatus().message).toContain("network or VPN");
    expect(api.release).toHaveBeenCalledTimes(1);
    const reads = api.read.mock.calls.length;
    await vi.advanceTimersByTimeAsync(30000);
    expect(api.read).toHaveBeenCalledTimes(reads);
  });
  it("keeps healthy brokers live when another broker fails, including quiet connections", async () => {
    const { source, api } = harness();
    source.configure({
      ...document,
      connections: [
        ...document.connections,
        { ...document.connections[0]!, id: "second" },
      ],
    }, 7, "user1", true);
    const mixed = batch({
      connections: [
        batch().connections[0]!,
        { ...batch().connections[0]!, connection_id: "second", state: "error" },
      ],
      streams: [],
      samples: [],
    });
    api.create.mockResolvedValue(lease(mixed));
    api.read.mockResolvedValue(mixed);
    await source.start();
    await vi.advanceTimersByTimeAsync(60000);
    expect(source.getStatus()).toMatchObject({ phase: "live", active: true });
    expect(api.release).not.toHaveBeenCalled();
    source.stop();
  });
  it("stops repeated API failures", async () => {
    const { source, api } = harness();
    api.read.mockRejectedValue(new Error("offline"));
    await source.start();
    await vi.advanceTimersByTimeAsync(20000);
    expect(source.getStatus()).toMatchObject({ phase: "error", active: false });
    expect(api.release).toHaveBeenCalledTimes(1);
    const reads = api.read.mock.calls.length;
    await vi.advanceTimersByTimeAsync(30000);
    expect(api.read).toHaveBeenCalledTimes(reads);
  });
  it("stops a renewal outage even when polling still succeeds", async () => {
    const { source, api } = harness();
    api.renew.mockRejectedValue(new Error("offline"));
    await source.start();
    await vi.advanceTimersByTimeAsync(35000);
    expect(source.getStatus()).toMatchObject({ phase: "error", active: false });
    expect(source.getStatus().message).toContain("could not be renewed");
    expect(api.release).toHaveBeenCalledTimes(1);
    source.stop();
  });
  it("times out a hanging creation and releases its eventual lease", async () => {
    const { source, api } = harness();
    let resolve!: (value: LiveLease) => void;
    api.create.mockImplementation(
      () => new Promise<LiveLease>((done) => { resolve = done; }),
    );
    const start = source.start();
    await vi.advanceTimersByTimeAsync(20000);
    expect(source.getStatus()).toMatchObject({ phase: "error", active: false });
    resolve(lease());
    await start;
    expect(api.release).toHaveBeenCalledWith("lease");
    expect(api.read).not.toHaveBeenCalled();
    expect(api.renew).not.toHaveBeenCalled();
  });
  it("requires explicit start, polls sequentially and renews the owned lease", async () => {
    const { source, api } = harness();
    expect(api.create).not.toHaveBeenCalled();
    await source.start();
    await vi.advanceTimersByTimeAsync(15000);
    expect(api.create).toHaveBeenCalledWith(7, undefined);
    expect(api.read).toHaveBeenCalledTimes(16);
    expect(api.renew).toHaveBeenCalledTimes(1);
    source.stop();
    expect(api.release).toHaveBeenCalledWith("lease");
    const reads = api.read.mock.calls.length;
    await vi.advanceTimersByTimeAsync(30000);
    expect(api.read).toHaveBeenCalledTimes(reads);
    expect(source.getSnapshot("temperature")).toBeUndefined();
  });
  it("lets members observe without starting or renewing a lease", async () => {
    const { source, api } = harness(false);
    await source.start();
    await vi.advanceTimersByTimeAsync(16000);
    expect(api.read).toHaveBeenCalled();
    expect(api.create).not.toHaveBeenCalled();
    expect(api.renew).not.toHaveBeenCalled();
    expect(source.getStatus().observing).toBe(true);
    source.stop();
    expect(api.release).not.toHaveBeenCalled();
  });
  it("releases a late creation response after leaving the workspace", async () => {
    const { source, api } = harness();
    let resolve!: (value: LiveLease) => void;
    api.create.mockImplementation(
      () =>
        new Promise<LiveLease>((done) => {
          resolve = done;
        }),
    );
    const start = source.start();
    source.stop();
    resolve(lease());
    await start;
    expect(api.release).toHaveBeenCalledWith("lease");
    expect(api.read).not.toHaveBeenCalled();
    expect(source.getStatus().phase).toBe("idle");
  });
  it("releases while hidden and resumes only an explicitly requested preview", async () => {
    const { source, api } = harness();
    source.pause();
    source.resume();
    expect(api.create).not.toHaveBeenCalled();
    await source.start();
    source.pause();
    expect(source.getStatus().phase).toBe("paused");
    expect(api.release).toHaveBeenCalledWith("lease");
    expect(source.getSnapshot("temperature")?.samples).toHaveLength(1);
    source.resume();
    await vi.advanceTimersByTimeAsync(0);
    expect(api.create).toHaveBeenCalledTimes(2);
    source.stop();
    source.resume();
    expect(api.create).toHaveBeenCalledTimes(2);
  });
  it("recovers network failures and stops on revoked authorization", async () => {
    const { source, api } = harness();
    api.read.mockRejectedValueOnce(new Error("offline"));
    await source.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(source.getStatus().phase).toBe("reconnecting");
    await vi.advanceTimersByTimeAsync(3000);
    expect(source.getStatus().phase).toBe("live");
    api.read.mockRejectedValueOnce(new ApiRequestError("Session expired", 401));
    await vi.advanceTimersByTimeAsync(1000);
    expect(source.getStatus()).toMatchObject({ phase: "error", active: false });
    expect(api.release).toHaveBeenCalledWith("lease");
    source.stop();
  });
  it("requests reconnect when the backend definition changes", async () => {
    const { source, api } = harness();
    api.read.mockResolvedValue(batch({ revision: 8 }));
    await source.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(source.getStatus()).toMatchObject({ phase: "error", active: false });
    expect(source.getStatus().message).toContain("saved system changed");
    expect(source.getSnapshot("temperature")).toBeUndefined();
    source.stop();
  });
});
