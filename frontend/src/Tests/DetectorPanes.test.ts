import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useDetectorPanes } from "@/hooks/use-detector-panes";
import type { ActiveService, MonitoringChartEvidence } from "@/types/monitoring";

const service = (status: boolean, stage = "operational") =>
  ({ id: "svc", status, operational_status: { stage, is_stale: false } }) as unknown as ActiveService;
const scored = (time: number) =>
  ({ service_id: "svc", timestamp: new Date(time).toISOString(), sensor_set: ["temp"], input_timestamps: { temp: new Date(time).toISOString() },
    tracker_results: [] }) as unknown as MonitoringChartEvidence;
const panes = (options: Partial<Parameters<typeof useDetectorPanes>[0]>) => renderHook(() => useDetectorPanes({
  telemetryType: "temp", evidence: [], telemetryTimes: [], pendingCandidateTimes: [1000, 2000, 3000], selectionKey: "temp",
  ...options,
})).result.current;

describe("useDetectorPanes", () => {
  it("awaits the first score of an operational service", () => {
    const result = panes({ service: service(true) });
    expect(result.operational).toBe(true);
    expect(result.awaitingFirstScore).toBe(true);
    expect(result.pending).toEqual([]);
  });

  it("counts observations newer than the last score as pending", () => {
    const evidence = [scored(1500)];
    const result = panes({ service: service(true), evidence });
    expect(result.lastScoreTime).toBe(1500);
    expect(result.pending).toEqual([2000, 3000]);
  });

  it("treats a stopped service as operational only when asked to", () => {
    expect(panes({ service: service(false) }).operational).toBe(false);
    expect(panes({ service: service(false), requireActiveService: false }).operational).toBe(true);
    expect(panes({ service: service(true, "warming_up") }).operational).toBe(false);
    expect(panes({}).operational).toBe(false);
  });
});
