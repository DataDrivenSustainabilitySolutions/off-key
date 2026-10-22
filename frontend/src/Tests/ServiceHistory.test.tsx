import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useServiceHistory } from "@/features/monitoring/useServiceHistory";
import { ReadingHistoryCache } from "@/domain/readings/readingHistoryCache";
import type { MonitoringInput } from "@/domain/monitoring/serviceModel";
import { getTelemetryData } from "@/lib/charger-api";
import { apiUtils } from "@/lib/api-client";
import type { MonitoringChartEvidence } from "@/types/monitoring";
import type { TelemetryDataPoint } from "@/types/charger";

vi.mock("@/lib/charger-api", async original => ({ ...await original<typeof import("@/lib/charger-api")>(), getTelemetryData: vi.fn() }));
vi.mock("@/lib/api-client", async original => ({ ...await original<typeof import("@/lib/api-client")>(), apiUtils: { get: vi.fn() } }));
const connection = { id: "broker", label: "Broker", protocol: "mqtt" as const, host: "example.test", port: 1883, transport: "tcp" as const, tls: false };
const inputs: MonitoringInput[] = ["temperature", "humidity"].map(id => ({
  stream: { id, label: id, connection_id: "broker", topic: id, category: "Other", value_type: "number" },
  binding: { entity_id: "entity", telemetry_key: id, accepted_topic: id, policy: { mode: "original", interval_seconds: 1 } }, path: "Station",
}));
const timestamp = "2026-10-21T12:00:00.000Z";
const evidence: MonitoringChartEvidence = { service_id: "forest", timestamp, created: timestamp, sequence_number: 1,
  sensor_set: ["temperature", "humidity"], input_timestamps: { temperature: timestamp, humidity: timestamp },
  strategy: "adaptive_stream", anomaly_score: 0.7, restarted_martingale: null, threshold: 0.6, alarm: true };

beforeEach(() => {
  vi.mocked(getTelemetryData).mockResolvedValue([{ timestamp, value: 20 }]);
  vi.mocked(apiUtils.get).mockResolvedValue([evidence]);
});

describe("service history polling", () => {
  it("fetches each input but only one service-scoped evidence page for their shared entity", async () => {
    const { result, rerender } = renderHook(({ selected }) => useServiceHistory("forest", selected, inputs, [connection]), { initialProps: { selected: inputs } });
    await waitFor(() => expect(result.current.monitoring.evidence).toEqual([evidence]));
    expect(getTelemetryData).toHaveBeenCalledTimes(2);
    expect(apiUtils.get).toHaveBeenCalledTimes(1);
    expect(vi.mocked(apiUtils.get).mock.calls[0]![0]).toContain("service_id=forest");
    expect([...result.current.histories.values()].every(item => item.telemetry.length === 1)).toBe(true);
    rerender({ selected: inputs.map(input => ({ ...input })) });
    await act(async () => { await Promise.resolve(); });
    expect(apiUtils.get).toHaveBeenCalledTimes(1);
    expect(getTelemetryData).toHaveBeenCalledTimes(2);
  });

  it("keeps complete joint evidence when the displayed reading selection changes", async () => {
    const { result, rerender } = renderHook(({ selected }) => useServiceHistory("forest", selected, inputs, [connection]), { initialProps: { selected: inputs } });
    await waitFor(() => expect(result.current.monitoring.evidence).toEqual([evidence]));
    rerender({ selected: [inputs[0]!] });
    await waitFor(() => expect(result.current.histories.size).toBe(1));
    expect(result.current.monitoring.evidence[0]!.sensor_set).toEqual(["temperature", "humidity"]);
    expect(result.current.monitoring.evidence[0]!.anomaly_score).toBe(0.7);
  });

  it("aborts detached requests and never restores their results into the workspace cache", async () => {
    let completeReadings!: (points: TelemetryDataPoint[]) => void;
    let completeEvidence!: (rows: MonitoringChartEvidence[]) => void;
    vi.mocked(getTelemetryData).mockReturnValue(new Promise(resolve => { completeReadings = resolve; }));
    vi.mocked(apiUtils.get).mockReturnValue(new Promise(resolve => { completeEvidence = resolve; }));
    const cache = new ReadingHistoryCache("member-one");
    const { unmount } = renderHook(() => useServiceHistory("forest", [inputs[0]!], inputs, [connection], cache));
    const signal = vi.mocked(getTelemetryData).mock.calls[0]![2]!;
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => { completeReadings([{ timestamp, value: 99 }]); completeEvidence([evidence]); });
    expect(cache.revision).toBe(0);
  });
});
