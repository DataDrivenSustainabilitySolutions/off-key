import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiUtils } from "@/lib/api-client";
import { mergeReadingHistory } from "@/domain/readings/readingMonitoring";
import { useReadingMonitoring } from "@/features/readings/useReadingMonitoring";
import { EMPTY_READING_HISTORY, ReadingHistoryCache, READING_HISTORY_CACHE_LIMIT, READING_HISTORY_POINT_LIMIT } from "@/domain/readings/readingHistoryCache";
import type { SystemConnection, SystemStream } from "@/types/system";

vi.mock("@/lib/api-client", () => ({ apiUtils: { get: vi.fn() } }));
const connection: SystemConnection = { id: "broker", label: "Building", protocol: "mqtt", host: "broker.test", port: 1883, transport: "tcp", tls: false };
const stream: SystemStream = { id: "reading", label: "Temperature", connection_id: "broker", topic: "site/room/air", value_type: "number", category: "Environment" };
const savedBinding = { entity_id: "canonical-entity", telemetry_key: "temperature/air", accepted_topic: "telemetry/canonical-entity/temperature/air", policy: { mode: "original" as const, interval_seconds: 10 } };
const time = "2026-10-10T12:00:00Z";
const points = [{ timestamp: time, created: time, value: 22 }];
const evidence = [{ service_id: "monitor", timestamp: time, created: time, sequence_number: 1,
  input_timestamps: { "temperature/air": time }, sensor_set: ["temperature/air"],
  strategy: "adaptive_stream", anomaly_score: 2, threshold: 3, alarm: false, restarted_martingale: null }];

beforeEach(() => {
  vi.mocked(apiUtils.get).mockReset();
  vi.mocked(apiUtils.get).mockImplementation(async (endpoint) => {
    if (endpoint.includes("/data?")) return points;
    if (endpoint.includes("/evidence/chart?")) return evidence;
    if (endpoint.startsWith("/v1/anomalies?")) return [];
    if (endpoint.startsWith("/v1/monitors/workspace")) return { services: [], authoring_enabled: false };
    throw new Error("Unexpected endpoint");
  });
});

describe("reading monitoring identity and history", () => {
  it("sorts and bounds history, updates corrected samples, and discards invalid points", () => {
    expect(mergeReadingHistory([{ timestamp: time, value: 20 }], [
      { timestamp: "2026-10-10T12:00:01Z", value: 23 }, { timestamp: time, value: 22 },
      { timestamp: "invalid", value: 4 }, { timestamp: "2026-10-10T12:00:02Z", value: NaN },
    ], 1)).toEqual([{ timestamp: "2026-10-10T12:00:01Z", value: 23 }]);
  });
});

describe("selected-reading monitoring subscription", () => {
  it("shows recorded values before a slow evidence request finishes", async () => {
    const baseGet = vi.mocked(apiUtils.get).getMockImplementation()!;
    vi.mocked(apiUtils.get).mockImplementation((endpoint, options) => endpoint.includes("/evidence/chart?")
      ? new Promise(() => {}) : baseGet(endpoint, options));
    const hook = renderHook(() => useReadingMonitoring(connection, stream, savedBinding));
    await waitFor(() => expect(hook.result.current.telemetry).toEqual(points));
    expect(hook.result.current.loading).toBe(false);
    expect(hook.result.current.evidence).toEqual([]);
  });

  it("opens previously viewed history immediately, catches up, and isolates other inputs and accounts", async () => {
    const cache = new ReadingHistoryCache("account-one");
    const first = renderHook(() => useReadingMonitoring(connection, stream, savedBinding, cache));
    await waitFor(() => expect(first.result.current.telemetry).toEqual(points));
    first.unmount();
    const baseGet = vi.mocked(apiUtils.get).getMockImplementation()!;
    let resolve: (value: unknown) => void = () => {};
    vi.mocked(apiUtils.get).mockImplementation((endpoint, options) => endpoint.includes("/data?")
      ? new Promise(done => { resolve = done; }) : baseGet(endpoint, options));
    const returned = renderHook(({ reading, store }) => useReadingMonitoring(connection, reading, savedBinding, store),
      { initialProps: { reading: stream, store: cache } });
    expect(returned.result.current.telemetry).toEqual(points);
    await act(async () => { await Promise.resolve(); });
    const next = { timestamp: "2026-10-10T12:00:01Z", created: "2026-10-10T12:00:01Z", value: 24 };
    await act(async () => { resolve([next]); });
    expect(returned.result.current.telemetry).toEqual([...points, next]);
    returned.rerender({ reading: { ...stream, topic: "site/other/input" }, store: cache });
    expect(returned.result.current.telemetry).toEqual([]);
    returned.rerender({ reading: stream, store: new ReadingHistoryCache("account-two") });
    expect(returned.result.current.telemetry).toEqual([]);
  });

  it("bounds cached history during repeated navigation through a large catalogue", () => {
    const cache = new ReadingHistoryCache("account-one");
    for (let input = 0; input < 200; input++) cache.update(String(input), () => ({ data: {
      ...EMPTY_READING_HISTORY, telemetry: Array.from({ length: 4096 }, () => points[0]!), loading: false,
    } }));
    const entries = Array.from({ length: 200 }, (_, index) => cache.get(String(index))).filter(entry => entry !== undefined);
    expect(entries.length).toBeLessThanOrEqual(READING_HISTORY_CACHE_LIMIT);
    expect(entries.reduce((count, entry) => count + entry.data.telemetry.length + entry.data.evidence.length, 0)).toBeLessThanOrEqual(READING_HISTORY_POINT_LIMIT);
    expect(cache.get("0")).toBeUndefined();
    expect(cache.get("199")?.data.telemetry).toHaveLength(4096);
  });

  it("loads only the selected reading and keeps its binding through display-name edits", async () => {
    const hook = renderHook(({ reading }) => useReadingMonitoring(connection, reading, savedBinding), { initialProps: { reading: stream } });
    await waitFor(() => expect(hook.result.current.evidence).toHaveLength(1));
    expect(hook.result.current.telemetry).toEqual(points);
    const telemetryRequests = vi.mocked(apiUtils.get).mock.calls.filter(([endpoint]) => endpoint.includes("/data?"));
    expect(telemetryRequests).toHaveLength(1);
    expect(telemetryRequests[0]![0]).toContain("type=temperature%2Fair");
    hook.rerender({ reading: { ...stream, label: "Renamed on the fly" } });
    expect(vi.mocked(apiUtils.get).mock.calls.filter(([endpoint]) => endpoint === "/v1/system")).toHaveLength(0);
    hook.unmount();
    expect(vi.mocked(apiUtils.get).mock.calls[0]![1]?.signal?.aborted).toBe(true);
  });

  it("does not request unrelated stored telemetry when no input matches", async () => {
    renderHook(() => useReadingMonitoring(connection, { ...stream, topic: "site/other/input" }));
    await act(async () => { await Promise.resolve(); });
    expect(apiUtils.get).toHaveBeenCalledTimes(0);
  });

  it("aborts old selections and ignores responses arriving after selection changes", async () => {
    let resolve: (value: unknown) => void = () => {};
    vi.mocked(apiUtils.get).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const hook = renderHook(({ reading }) => useReadingMonitoring(connection, reading, savedBinding), { initialProps: { reading: stream } });
    const signal = vi.mocked(apiUtils.get).mock.calls[0]![1]!.signal;
    hook.rerender({ reading: { ...stream, topic: "site/other/input" } });
    await act(async () => { resolve(points); });
    expect(signal?.aborted).toBe(true);
    expect(hook.result.current.binding).toEqual({ entityId: savedBinding.entity_id, telemetryType: savedBinding.telemetry_key });
    expect(hook.result.current.telemetry).toEqual(points);
    // Three history requests per selection; the service list is one shared request.
    expect(apiUtils.get).toHaveBeenCalledTimes(7);
  });

  it("filters the shared service list to the reading's accepted topic", async () => {
    const baseGet = vi.mocked(apiUtils.get).getMockImplementation()!;
    vi.mocked(apiUtils.get).mockImplementation((endpoint, options) => endpoint.startsWith("/v1/monitors/workspace")
      ? Promise.resolve({ services: [
        { id: "match", mqtt_topics: ["telemetry/canonical-entity/#"] },
        { id: "other", mqtt_topics: ["telemetry/other-entity/#"] },
      ] }) : baseGet(endpoint, options));
    const hook = renderHook(() => useReadingMonitoring(connection, stream, savedBinding));
    await waitFor(() => expect(hook.result.current.services.map(service => service.id)).toEqual(["match"]));
    expect(vi.mocked(apiUtils.get).mock.calls.filter(([endpoint]) => endpoint.startsWith("/v1/monitors/workspace"))).toHaveLength(1);
  });

  it("polls with ingestion cursors, pauses in hidden tabs, and recovers from partial failures", async () => {
    vi.useFakeTimers();
    const baseGet = vi.mocked(apiUtils.get).getMockImplementation()!;
    let fail = true;
    vi.mocked(apiUtils.get).mockImplementation((endpoint, options) => {
      if (fail && endpoint.includes("/evidence/chart?")) return Promise.reject(new Error("Temporarily unavailable"));
      return baseGet(endpoint, options);
    });
    const hook = renderHook(() => useReadingMonitoring(connection, stream, savedBinding));
    await act(async () => { await Promise.resolve(); });
    expect(hook.result.current.telemetry).toEqual(points);
    expect(hook.result.current.error).toContain("could not be updated");
    fail = false;
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(hook.result.current.evidence).toHaveLength(1);
    expect(hook.result.current.error).toBe("");
    expect(vi.mocked(apiUtils.get).mock.calls.filter(([endpoint]) => endpoint.includes("/data?"))[1]![0]).toContain("after_created=");
    const visible = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    const count = vi.mocked(apiUtils.get).mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(apiUtils.get).toHaveBeenCalledTimes(count);
    visible.mockReturnValue(false);
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(apiUtils.get).toHaveBeenCalledTimes(count + 4);
    expect(vi.mocked(apiUtils.get).mock.calls.find(([endpoint]) => endpoint.includes("/evidence/chart?") && endpoint.includes("after_sequence_number="))).toBeDefined();
  });
});
