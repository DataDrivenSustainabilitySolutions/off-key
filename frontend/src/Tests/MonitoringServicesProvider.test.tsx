import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiUtils } from "@/lib/api-client";
import { MonitoringServicesProvider } from "@/domain/monitoring/MonitoringServicesProvider";
import { useMonitoringServices } from "@/domain/monitoring/useMonitoringServices";

vi.mock("@/lib/api-client", () => ({ apiUtils: { get: vi.fn(), patch: vi.fn() } }));

function Consumer({ interval, label }: { interval: number; label: string }) {
  const { services } = useMonitoringServices(true, interval);
  return <p>{label}: {services.length}</p>;
}

const requests = () => vi.mocked(apiUtils.get).mock.calls.filter(([endpoint]) => endpoint.startsWith("/v1/monitors/workspace")).length;

describe("shared monitoring service poll", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(apiUtils.get).mockReset();
    vi.mocked(apiUtils.get).mockResolvedValue({ services: [{ id: "a" }], authoring_enabled: false });
  });
  afterEach(() => { vi.useRealTimers(); });

  it("polls once for all consumers at the shortest interval and stops without consumers", async () => {
    const view = render(<MonitoringServicesProvider enabled>
      <Consumer interval={20_000} label="slow" /><Consumer interval={5_000} label="fast" />
    </MonitoringServicesProvider>);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(view.getByText("slow: 1")).toBeTruthy();
    expect(view.getByText("fast: 1")).toBeTruthy();
    const first = requests();
    expect(first).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(requests() - first).toBe(2);
    view.rerender(<MonitoringServicesProvider enabled>{null}</MonitoringServicesProvider>);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const stopped = requests();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(requests()).toBe(stopped);
  });
});
